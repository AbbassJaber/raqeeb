const BEATS = 7;                 // 0 boot .. 6 alert
const BEAT_MS = 2000;            // auto-play interval per beat
const body = document.body;
let runId = null, beat = 0, playing = false, timer = null, run = null;
let manifest = null, overviewMap = null, pinLayer = null, aoiLayer = null, markerById = {};
let chatHistory = [];                 // [{role, text}] for follow-up context
let liveMode = false, liveTick = 0;   // streaming a real agent run vs. cached playback
let animate = null;              // Motion (motion.dev) — loaded from CDN, optional
// severity heat ramp — monotonic green→gold→orange→red, deliberately NOT the brand blue
const TIER_COLOR = { critical: '#e5484d', high: '#ef8b3c', medium: '#e0a83a', low: '#57c59a' };
const SCAN_MAX_KM = 5;   // mirror config.SCAN_MAX_KM — keep ad-hoc scans near 10 m/pixel

const $ = (id) => document.getElementById(id);

async function loadMotion() {
  // Framer-Motion-grade springs/counters with no build step. Falls back to the
  // CSS animations already in styles.css if the CDN is unreachable (offline-safe).
  try {
    const m = await import("https://cdn.jsdelivr.net/npm/motion@11.13.5/+esm");
    animate = m.animate;
  } catch (e) {
    console.warn("Motion CDN unavailable — using CSS fallback.", e);
  }
}

async function init() {
  await loadMotion();
  manifest = await loadManifest();
  if (!manifest || !manifest.runs.length) {
    $('status').textContent = 'no cached run — run scripts/build_demo_run.py';
    return;
  }
  const picker = $('picker');
  manifest.runs.forEach(r => {
    const o = document.createElement('option');
    o.value = r.id; o.textContent = r.title; picker.appendChild(o);
  });
  picker.onchange = () => openRun(picker.value);
  $('run').onclick = () => { if (runId) runAgentic({ preset: runId }); };  // the one run mode: agentic, live
  $('toOverview').onclick = showOverview;
  $('scanBtn').onclick = startDraw;
  $('reviewedChk').onchange = e => { $('prepareBtn').disabled = !e.target.checked; };
  $('prepareBtn').onclick = prepareAlert;
  $('frClear').onclick = () => setReview(disposition() === 'cleared' ? 'pending' : 'cleared');
  $('frConfirm').onclick = () => setReview(disposition() === 'confirmed' ? 'pending' : 'confirmed');
  $('chatFab').onclick = () => $('chat').classList.toggle('open');
  $('chatClose').onclick = () => $('chat').classList.remove('open');
  $('chatForm').onsubmit = e => { e.preventDefault(); sendChat($('chatInput').value); };
  $('chatSuggest').querySelectorAll('.chip').forEach(ch => ch.onclick = () => sendChat(ch.textContent));
  $('introStart').onclick = hideIntro;
  $('helpBtn').onclick = showIntro;
  $('intro').onclick = e => { if (e.target === $('intro')) hideIntro(); };  // click backdrop to dismiss
  try { if (!sessionStorage.getItem('rqIntro')) showIntro(); } catch (_) { showIntro(); }
  document.addEventListener('keydown', onKey);
  setupSwipe();
  showOverview();      // land on the watchroom (queue + map)
  buildOverview();     // build the Leaflet map now that the overview is visible
  refreshLiveBadge();
  renderEval();        // measured accuracy on the labelled real-site set
}

// watchroom validation chip: real precision/recall/F1 from the accuracy harness
function renderEval() {
  const el = $('evalBadge'); if (!el) return;
  const pct = x => x == null ? '—' : Math.round(x * 100) + '%';
  fetch('/api/eval').then(r => r.json()).then(e => {
    if (!e.available || e.precision == null) { el.textContent = ''; return; }
    el.innerHTML = `<span class="eval-dot"></span>Validated · P ${pct(e.precision)} · `
      + `R ${pct(e.recall)} · F1 ${e.f1 != null ? e.f1.toFixed(2) : '—'}`
      + `<span class="eval-n"> on ${e.n} real sites</span>`;
    el.title = `${e.mode} benchmark, ${e.classifier} (first-pass, pre human review): `
      + `TP ${e.tp} · FP ${e.fp} · FN ${e.fn} · TN ${e.tn}. ${e.note || ''}`;
  }).catch(() => { el.textContent = ''; });
}

// header badge: is the agent wired to real satellite + AI, or the offline demo?
function refreshLiveBadge() {
  const b = $('liveBadge'); if (!b) return;
  fetch('/api/health').then(r => r.json()).then(h => {
    if (h.offline) {
      b.textContent = '○ Demo mode · synthetic pipeline';
      b.className = 'livebadge mono off';
    } else {
      b.textContent = '● Live · Sentinel-2 + ' + (h.provider === 'gemini' ? 'Gemini' : 'AI');
      b.className = 'livebadge mono on';
    }
  }).catch(() => { b.textContent = ''; });
}

async function loadManifest() {
  // prefer the live endpoint (reflects fresh scans); fall back to the static file
  return await fetch('/api/manifest').then(r => (r.ok ? r.json() : Promise.reject()))
    .catch(() => fetch('runs/manifest.json').then(r => r.json()).catch(() => null));
}

// --- national overview map --------------------------------------------------
function buildOverview() {
  if (typeof L === 'undefined') {   // Leaflet CDN unreachable — fall back to the player
    openRun(manifest.default || manifest.runs[0].id);
    return;
  }
  const baseMaps = {
    // Satellite is a hybrid: Esri imagery + a transparent place-names/boundaries layer on
    // top, so area names show (the other basemaps already carry labels). Labels sit in the
    // tile pane, below the candidate pins/overlays.
    'Satellite': L.layerGroup([
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Imagery © Esri', maxZoom: 19 }),
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Labels © Esri', maxZoom: 19 }),
    ]),
    'Dark': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      { attribution: '© OpenStreetMap · © CARTO', subdomains: 'abcd', maxZoom: 19 }),
    'Streets': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { attribution: '© OpenStreetMap', maxZoom: 19 }),
    'Light': L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      { attribution: '© OpenStreetMap · © CARTO', subdomains: 'abcd', maxZoom: 19 }),
  };
  const map = L.map('map', { zoomControl: true, layers: [baseMaps.Satellite] }).setView([33.85, 35.75], 9);
  pinLayer = L.layerGroup().addTo(map);     // candidate pins (on)
  aoiLayer = L.layerGroup();                // monitored-area footprints (off by default)
  overviewMap = map;
  renderPins(true);
  renderAOIs();
  const overlays = { 'Candidates': pinLayer, 'Monitored areas': aoiLayer };
  const ctl = L.control.layers(baseMaps, overlays, { collapsed: true }).addTo(map);
  addDrawControl(map);
  // reference context layers (added to the switcher once fetched; off until toggled)
  fetch('/api/reference').then(r => (r.ok ? r.json() : Promise.reject())).then(ref => {
    const styles = {
      protected: { color: '#3fb8a0', fillColor: '#3fb8a0', fillOpacity: 0.12, weight: 2 },
      permitted: { color: '#e0a83a', weight: 2, dashArray: '4 3', fill: false },
      coastline: { color: '#46c0b0', weight: 2 },
    };
    [['coastline', 'Coastline (national boundary)'], ['protected', 'Protected areas (WDPA)'],
     ['permitted', 'Permitted zones (proxy)']].forEach(([k, name]) => {
      if (ref[k]) ctl.addOverlay(L.geoJSON(ref[k], {
        style: styles[k],
        onEachFeature: (f, lyr) => {
          const p = f.properties || {};
          const t = p.name_en || p.name || p.desig;
          if (t) lyr.bindTooltip(t, { sticky: true });
        },
      }), name);
    });
  }).catch(() => {});
}

// monitored-area footprints (each case's AOI square, from centroid + area)
function renderAOIs() {
  if (!aoiLayer) return;
  aoiLayer.clearLayers();
  manifest.runs.forEach(r => {
    if (!r.centroid || !r.aoi_km2) return;
    const [lon, lat] = r.centroid, half = Math.sqrt(r.aoi_km2) / 2;
    const dlat = half / 111, dlon = half / (111 * Math.cos(lat * Math.PI / 180));
    L.rectangle([[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]],
      { color: TIER_COLOR[r.tier] || '#8aa0c0', weight: 1, fill: false, dashArray: '3 3' })
      .bindTooltip(r.title, { direction: 'top' }).addTo(aoiLayer);
  });
}

function renderPins(fit) {
  if (!pinLayer) return;
  pinLayer.clearLayers();
  markerById = {};
  const pts = [];
  manifest.runs.forEach(r => {
    if (!r.centroid) return;
    const [lon, lat] = r.centroid, color = TIER_COLOR[r.tier] || '#8aa0c0';
    pts.push([lat, lon]);
    const m = L.circleMarker([lat, lon],
      { radius: 9, color, fillColor: color, fillOpacity: .85, weight: 2, className: 'rq-pin' }).addTo(pinLayer);
    const tier = r.tier ? r.tier.toUpperCase() : 'n/a', score = r.score != null ? ` · ${r.score}/100` : '';
    m.bindPopup(
      `<img class="pop-thumb" src="runs/${r.id}/after.png" alt="">` +
      `<b>${r.title}</b><br><span class="pop-tier" style="color:${color}">${tier}${score}</span>` +
      `<br>${r.flags} rule${r.flags === 1 ? '' : 's'} flagged<br>` +
      `<span class="pop-open" data-id="${r.id}">▶ open dossier</span>`);
    m.on('popupopen', e => {
      const el = e.popup.getElement().querySelector('.pop-open');
      if (el) el.onclick = () => openRun(r.id);
    });
    m.on('mouseover', () => highlightCard(r.id, true));
    m.on('mouseout', () => highlightCard(r.id, false));
    markerById[r.id] = m;
  });
  if (fit && pts.length) overviewMap.fitBounds(pts, { padding: [60, 60], maxZoom: 11 });
}

function highlightPin(id, on) {
  const m = markerById[id]; if (!m) return;
  m.setStyle({ radius: on ? 13 : 9, weight: on ? 4 : 2 });
  if (on) m.bringToFront();
}
function highlightCard(id, on) {
  const card = document.querySelector(`#queueList .qcard[data-id="${id}"]`);
  if (!card) return;
  card.classList.toggle('hot', on);
  if (on) card.scrollIntoView({ block: 'nearest' });
}

function addDrawControl(map) {
  if (typeof L.Control === 'undefined' || !L.Control.Draw) return;  // leaflet-draw CDN missing
  const drawn = new L.FeatureGroup().addTo(map);
  map.addControl(new L.Control.Draw({
    position: 'topleft', edit: false,
    draw: { rectangle: { shapeOptions: { color: '#6ea8fe', weight: 2 } },
            polygon: false, polyline: false, circle: false, marker: false, circlemarker: false },
  }));

  // live size guidance while drawing: show the box's km, green within range / red past the cap
  let drawing = false, corner1 = null;
  const sidesKm = (a, b) => [
    Math.abs(b.lng - a.lng) * 111 * Math.cos(a.lat * Math.PI / 180),
    Math.abs(b.lat - a.lat) * 111];
  map.on(L.Draw.Event.DRAWSTART, () => {
    drawing = true; corner1 = null;
    showDrawHud(`Drag a box · 2–3 km is ideal (max ${SCAN_MAX_KM} km)`, '');
  });
  map.on(L.Draw.Event.DRAWSTOP, () => { drawing = false; corner1 = null; hideDrawHud(); });
  map.on('mousedown', e => { if (drawing) corner1 = e.latlng; });
  map.on('mousemove', e => {
    if (!drawing || !corner1) return;
    const [w, h] = sidesKm(corner1, e.latlng), side = Math.max(w, h);
    let cls = '', tag = '  · ok';
    if (side > SCAN_MAX_KM) { cls = 'bad'; tag = ` · too large (max ${SCAN_MAX_KM} km)`; }
    else if (side >= 2 && side <= 3) { cls = 'ideal'; tag = '  ✓ ideal'; }
    showDrawHud(`${w.toFixed(1)} × ${h.toFixed(1)} km${tag}`, cls);
  });

  map.on(L.Draw.Event.CREATED, e => {
    hideDrawHud();
    drawn.clearLayers(); drawn.addLayer(e.layer);
    const b = e.layer.getBounds(), c = b.getCenter();
    const [w, h] = sidesKm(b.getSouthWest(), b.getNorthEast()), sideKm = Math.max(w, h);
    if (sideKm > SCAN_MAX_KM) {   // keep detection at ~10 m/pixel + the fetch fast
      L.popup().setLatLng(c).setContent(
        `Zone too large (~${sideKm.toFixed(1)} km across). Draw ≤ ${SCAN_MAX_KM} km ` +
        `(2–3 km ideal) so detection stays at ~10 m/pixel.`).openOn(map);
      drawn.clearLayers();
      return;
    }
    runAgentic({ bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()],
                 mode: 'quarry', title: 'Drawn zone' });
  });
}

function startDraw() {   // "Scan a new area" → activate the rectangle tool on the map
  if (overviewMap && typeof L !== 'undefined' && L.Draw && L.Draw.Rectangle) {
    new L.Draw.Rectangle(overviewMap, { shapeOptions: { color: '#6ea8fe', weight: 2 } }).enable();
  }
}

// --- ranked candidate queue (the watchroom's left rail) ---------------------
function renderQueue() {
  const list = $('queueList'); if (!list) return;
  // active candidates first (by severity); cleared cases sink to the bottom
  const runs = [...manifest.runs].sort((a, b) => {
    const ac = a.review === 'cleared', bc = b.review === 'cleared';
    if (ac !== bc) return ac ? 1 : -1;
    return (b.score ?? -1) - (a.score ?? -1);
  });
  $('queueCount').textContent = `(${runs.length})`;
  const parts = [];
  ['critical', 'high', 'medium', 'low'].forEach(t => {
    const n = runs.filter(r => r.tier === t && r.review !== 'cleared').length; if (n) parts.push(`${n} ${t}`);
  });
  const unscored = runs.filter(r => !r.tier && r.review !== 'cleared').length;
  if (unscored) parts.push(`${unscored} unscored`);
  const cleared = runs.filter(r => r.review === 'cleared').length;
  if (cleared) parts.push(`${cleared} cleared`);
  // ops-console header: how much ground + when last looked
  const km2 = runs.reduce((s, r) => s + (r.aoi_km2 || 0), 0);
  const dates = runs.map(r => r.generated_at).filter(Boolean).sort();
  const last = dates.length ? new Date(dates[dates.length - 1]).toLocaleDateString(undefined,
    { month: 'short', day: 'numeric' }) : null;
  $('queueSummary').textContent = parts.join(' · ')
    + (km2 ? ` · watching ~${km2.toFixed(1)} km²` : '')
    + (last ? ` · last sweep ${last}` : '');
  list.innerHTML = '';
  if (!runs.length) {
    list.innerHTML = '<div class="queue-empty">No candidates yet. Draw a zone on the map ' +
      '(▢ top-left) or ask Raqeeb to scan one.</div>';
    return;
  }
  runs.forEach(r => {
    const color = TIER_COLOR[r.tier] || '#8aa0c0';
    const area = r.area_ha != null ? `${r.area_ha} ha · ` : '';
    const card = document.createElement('div');
    card.className = 'qcard' + (r.review === 'cleared' ? ' cleared' : '');
    card.dataset.id = r.id; card.tabIndex = 0;
    const flag = r.review === 'cleared' ? '<span class="qflag cleared">✓ normal</span>'
      : r.review === 'confirmed' ? '<span class="qflag confirmed">⚠ confirmed</span>' : '';
    card.innerHTML =
      `<span class="qstripe" style="background:${color}"></span>` +
      `<img class="qthumb" src="runs/${r.id}/after.png" alt="" loading="lazy">` +
      `<span class="qbody">` +
        `<span class="qtitle">${r.title}</span>` +
        `<span class="qmeta">${r.mode} · ${area}${r.flags} flagged</span>` +
        `<span class="qbar"><i style="width:${Math.max(2, r.score || 0)}%;background:${color}"></i></span>` +
      `</span>` +
      `<span class="qsev" style="color:${color}">${r.tier || 'unscored'}` +
        `${r.score != null ? `<b>${Math.round(r.score)}</b>` : ''}${flag}</span>` +
      `<button class="qdel" title="Remove this candidate" aria-label="Remove">×</button>`;
    card.onclick = () => openRun(r.id);
    card.onkeydown = e => { if (e.key === 'Enter') openRun(r.id); };
    card.onmouseenter = () => highlightPin(r.id, true);
    card.onmouseleave = () => highlightPin(r.id, false);
    card.querySelector('.qdel').onclick = e => { e.stopPropagation(); deleteCase(r.id, r.title); };
    list.appendChild(card);
  });
}

async function deleteCase(id, title) {
  if (!confirm(`Remove "${title}" from the queue? This deletes its cached analysis.`)) return;
  try {
    const r = await fetch(`/api/run/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!r.ok) throw new Error('delete failed');
  } catch (_) {
    alert('Could not delete — is the server running?');
    return;
  }
  if (runId === id) showOverview();
  manifest = await loadManifest();
  renderQueue();
  renderPins(false);
  renderAOIs();
}

function showDrawHud(text, cls) {   // cls: '' neutral · 'ideal' green · 'bad' red
  const h = $('drawHud'); if (!h) return;
  h.textContent = text; h.hidden = false;
  h.className = 'draw-hud mono' + (cls ? ' ' + cls : '');
}
function hideDrawHud() { const h = $('drawHud'); if (h) h.hidden = true; }

function showOverview() {
  stop(); liveMode = false;
  document.body.classList.remove('view-case');
  document.body.classList.add('view-home');
  $('overview').hidden = false; $('runview').hidden = true;
  $('status').innerHTML = '<span class="dot"></span>WATCHING';
  renderQueue();
  if (overviewMap) setTimeout(() => overviewMap.invalidateSize(), 0);
}

function enterCase() {
  document.body.classList.remove('view-home');
  document.body.classList.add('view-case');
  $('overview').hidden = true; $('runview').hidden = false;
}

async function openRun(id) {       // drill into a case — auto-play the analysis step by step
  enterCase();
  $('picker').value = id;
  await loadRun(id);               // ends at beat 0
  renderCaseMeta();
  play();                          // scan → detect → classify → legality → dossier → alert
}

// map a legality flag to its (proxy) legal basis, for the case facts
const LEGAL_BASIS = [
  [/setback|public.?domain|maritime|coastal/i, 'Maritime public domain · 150 m setback'],
  [/protected/i, 'Protected-area boundary'],
  [/permit/i, 'Outside any permitted quarry zone'],
];
function legalBasis(flags) {
  const t = (flags || []).join(' ');
  for (const [re, label] of LEGAL_BASIS) if (re.test(t)) return label;
  return null;
}

// case-file header + facts strip + severity + review gate, from the current `run`
function renderCaseMeta() {
  if (!run) return;
  $('caseTitle').textContent = run.title || run.id;
  const c = run.centroid;
  $('caseSub').textContent =
    `${run.mode || 'quarry'} · ${c ? `${c[1].toFixed(3)}°N ${c[0].toFixed(3)}°E · ` : ''}` +
    `S2 ${run.windows.before.slice(0, 4)} → ${run.windows.after.slice(0, 4)}`;
  renderFacts();
  renderSeverity();
  renderFieldReview();
  resetReview();
}

// onsite field-verification disposition (pending → cleared/confirmed)
function disposition() { return (run && run.field_review && run.field_review.status) || 'pending'; }

function renderFieldReview() {
  const fr = run && run.field_review, s = $('frStatus');
  $('frClear').classList.toggle('on', !!fr && fr.status === 'cleared');
  $('frConfirm').classList.toggle('on', !!fr && fr.status === 'confirmed');
  if (!s) return;
  if (!fr) { s.textContent = 'Not yet field-checked.'; return; }
  const word = fr.status === 'cleared' ? 'Verified normal — cleared' : 'Confirmed violation';
  s.textContent = `${fr.status === 'cleared' ? '✓' : '⚠'} ${word}${fr.at ? ' · ' + fr.at.slice(0, 10) : ''}`;
}

async function setReview(status) {
  if (!runId) return;
  try {
    const r = await fetch('/api/review', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: runId, status })
    }).then(r => r.json());
    if (!r.ok) throw new Error('save failed');
    run.field_review = r.review || null;
  } catch (_) {
    $('frStatus').textContent = 'Could not save — is the server running?';
    return;
  }
  renderFieldReview();
  renderFacts();
  refreshManifest();   // reflect the disposition in the queue
}

function renderFacts() {
  const facts = $('caseFacts'); if (!facts) return;
  const chips = [];
  const fr = run.field_review;
  if (fr) {                       // onsite verdict leads the facts strip
    const cleared = fr.status === 'cleared';
    chips.push(`<span class="fact ${cleared ? 'verdict-confirm' : 'verdict-reject'}">`
      + `${cleared ? '✓ verified normal (cleared)' : '⚠ confirmed onsite'}</span>`);
  }
  const so = run.second_opinion;
  if (so) {
    const v = { confirm: 'confirmed', downgrade: 'downgraded', reject: 'likely false' }[so.verdict] || so.verdict;
    const mark = so.verdict === 'confirm' ? '✓' : so.verdict === 'reject' ? '✕' : '↓';
    chips.push(`<span class="fact verdict-${so.verdict}" title="${(so.reason || '').replace(/"/g, '')}">${mark} 2nd opinion: ${v}</span>`);
  }
  const a = run.region && run.region.area_ha;
  if (a != null) chips.push(`<span class="fact">▦ ${a} ha · ${Math.round(a * 10000).toLocaleString()} m²</span>`);
  const d = run.distance_to_coast_m;
  if (d != null) chips.push(`<span class="fact">⌑ ${d <= 5 ? 'in the sea / at the shore' : Math.round(d) + ' m from coast'}</span>`);
  const conf = run.classification && run.classification.confidence;
  if (conf != null) chips.push(`<span class="fact">◴ confidence ${conf} · ${run.classification.source}</span>`);
  const basis = legalBasis(run.flags);
  if (basis) chips.push(`<span class="fact basis">§ ${basis}</span>`);
  facts.innerHTML = chips.join('');
}

function renderSeverity() {
  $('sevPanel').classList.remove('pending');
  const s = run.severity, chip = $('sevChip');
  if (!s) {
    chip.textContent = 'unscored'; chip.style.color = '#8aa0c0'; chip.style.borderColor = '';
    $('sevScore').textContent = '—'; $('sevTier').textContent = ''; $('sevFactors').innerHTML = '';
    const b = $('sevBar'); if (b) b.style.width = '0';
    return;
  }
  const color = TIER_COLOR[s.tier] || '#8aa0c0';
  chip.textContent = `${s.tier.toUpperCase()} · ${s.score}/100`;
  chip.style.color = color; chip.style.borderColor = color;
  $('sevScore').textContent = s.score; $('sevScore').style.color = color;
  $('sevTier').textContent = s.tier;
  const bar = $('sevBar');
  if (bar) { bar.style.width = Math.max(0, Math.min(100, s.score)) + '%'; bar.style.background = color; }
  $('sevFactors').innerHTML = (s.factors || []).map(f =>
    `<div class="sevf"><span>${f.label}</span><span>+${f.points}</span></div>`).join('');
}

function resetReview() {
  $('reviewedChk').checked = false;
  $('prepareBtn').disabled = true;
  $('revStatus').textContent = '';
  $('draft').classList.remove('ready');
  $('draft').textContent = '✉ Alert drafted — not sent';
}

async function prepareAlert() {        // human-gated: only fires after the checkbox + button
  if (!runId) return;
  $('prepareBtn').disabled = true;
  $('revStatus').textContent = 'preparing…';
  try {
    const r = await fetch('/api/alert', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: runId, reviewed: true })
    }).then(r => r.json());
    if (r.ok) {
      $('revStatus').textContent = '✓ ' + r.message;
      if (r.draft) { $('draft').textContent = r.draft; $('draft').classList.add('ready'); }
    } else {
      $('revStatus').textContent = r.detail || r.message || 'could not prepare alert';
    }
  } catch (e) {
    $('revStatus').textContent = 'live runs need the server — python scripts/run_server.py';
  }
}

// --- executive chat: grounded Q&A over the current candidates ----------------
function chatBubble(text, cls) {
  const d = document.createElement('div');
  d.className = 'chat-msg ' + cls;
  d.textContent = text;
  const log = $('chatLog');
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

// minimal, safe markdown: escape first, then bold / code / bullets / breaks
function mdToHtml(t) {
  const esc = (t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return esc
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/(^|\n)\s*[-•]\s+/g, '$1• ')
    .replace(/\n/g, '<br>');
}

async function sendChat(q) {
  q = (q || '').trim();
  if (!q) return;
  $('chatSuggest').style.display = 'none';
  $('chatInput').value = '';
  chatBubble(q, 'user');
  chatHistory.push({ role: 'user', text: q });
  const bot = chatBubble('thinking…', 'bot thinking');
  let data;
  try {
    data = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, history: chatHistory.slice(-8) })
    }).then(r => r.json());
  } catch (e) {
    bot.className = 'chat-msg bot';
    bot.textContent = 'The server isn’t running — start scripts/run_server.py.';
    return;
  }
  bot.className = 'chat-msg bot';
  bot.innerHTML = mdToHtml(data.answer || '(no answer)');
  chatHistory.push({ role: 'assistant', text: data.answer || '' });
  if (data.action && data.action.type === 'scan') {
    const wrap = document.createElement('div');
    wrap.className = 'chat-refs';
    const go = document.createElement('button');
    go.className = 'ref';
    go.textContent = '▶ Run this scan';
    go.onclick = () => { $('chat').classList.remove('open'); runAgentic(data.action.scenario); };
    wrap.appendChild(go);
    bot.appendChild(wrap);
  }
  if (data.cases && data.cases.length) {
    const refs = document.createElement('div');
    refs.className = 'chat-refs';
    data.cases.forEach(id => {
      const r = (manifest.runs || []).find(x => x.id === id) || {};
      const b = document.createElement('button');
      b.className = 'ref';
      b.textContent = '▸ ' + (r.title || id);
      b.onclick = () => { $('chat').classList.remove('open'); openRun(id); };
      refs.appendChild(b);
    });
    bot.appendChild(refs);
  }
  $('chatLog').scrollTop = $('chatLog').scrollHeight;
}

// --- live agent run: stream the real pipeline into the cinematic beats -------
function runAgentic(body) { return runLive(body, '/api/agent-run'); }

async function runLive(body, endpoint = '/api/run') {
  stop();
  liveMode = true; liveTick++;
  enterCase();
  $('status').innerHTML = '<span class="dot"></span>RUNNING';
  $('stageMsg').hidden = true; $('stageLoading').hidden = false;
  let resp;
  try {
    resp = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify(body) });
  } catch (e) {
    liveMode = false;
    $('stageLoading').hidden = true;
    $('status').innerHTML = '<span class="dot"></span>NO SERVER';
    $('stageMsg').textContent = 'Live runs need the server — run scripts/run_server.py.';
    $('stageMsg').hidden = false;
    return;
  }
  if (!resp.ok) {   // e.g. zone too large (422) — show the reason, don't hang
    liveMode = false;
    $('stageLoading').hidden = true;
    let msg = 'run rejected';
    try { msg = (await resp.json()).detail || msg; } catch (_) {}
    $('status').innerHTML = '<span class="dot"></span>BLOCKED';
    $('stageMsg').textContent = msg; $('stageMsg').hidden = false;
    $('caseSub').textContent = msg;
    return;
  }
  const reader = resp.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      const line = frame.split('\n').find(l => l.startsWith('data:'));
      if (line) { try { handleLive(JSON.parse(line.slice(5).trim())); } catch (_) {} }
    }
  }
}

function liveLog(text, flag) {
  if (!liveMode && beat >= 1) return;   // ignore stray late events
  const d = logLine(text, flag); d.classList.add('show');
  $('log').appendChild(d);
}

function liveStatus(t) { $('status').innerHTML = '<span class="dot"></span>' + t; }

function showIntro() { $('intro').hidden = false; }
function hideIntro() { $('intro').hidden = true; try { sessionStorage.setItem('rqIntro', '1'); } catch (_) {} }

// reveal every line in the inline reasoning panel (cached runs show the full trace at once)
function revealReasoning() {
  document.querySelectorAll('#log .l').forEach(l => l.classList.add('show'));
}

function handleLive(e) {
  switch (e.stage) {
    case 'agent':            // the LLM agent's reasoning (agentic run)
      liveLog('🧠 ' + e.line);
      break;
    case 'tool':             // a tool the agent chose to call
      liveLog('▸ ' + (e.name || '').replace(/_/g, ' '));
      break;
    case 'open':
      runId = e.id;
      run = { id: e.id, images: {}, region: null, classification: null, flags: [], overlays: [], narration: [] };
      $('log').innerHTML = ''; $('overlays').innerHTML = ''; $('caseFacts').innerHTML = '';
      $('ts').hidden = true; $('stageMsg').hidden = true;
      $('ndvi').style.color = 'var(--red-t)'; $('bsi').style.color = 'var(--amber)';
      $('dossierLink').removeAttribute('href'); $('dossierLink').textContent = '▤ dossier';
      $('clsLabel').textContent = '—'; $('caseTitle').textContent = 'Scanning…';
      $('sevChip').textContent = '—'; $('sevChip').style.color = ''; resetReview();
      $('telemetry').classList.add('pending'); $('sevPanel').classList.add('pending');
      $('sevScore').textContent = '·'; $('sevTier').textContent = 'analysing…';
      setBeat(0);
      break;
    case 'start':
      run.title = e.title; run.mode = e.mode; run.windows = e.windows;
      $('caseTitle').textContent = e.title;
      $('caseSub').textContent = `${e.mode} · S2 ${e.windows.before.slice(0, 4)} → ${e.windows.after.slice(0, 4)} · fetching…`;
      break;
    case 'imagery':
      $('stageLoading').hidden = true;
      run.images = { before: e.before, after: e.after, grid: e.grid };
      $('imgBefore').src = `runs/${runId}/${e.before}?t=${liveTick}`;
      $('imgAfter').src = `runs/${runId}/${e.after}?t=${liveTick}`;
      $('beforeTag').textContent = 'BEFORE'; $('afterTag').textContent = 'AFTER';
      liveLog('• Pulled before/after imagery');
      setBeat(1);
      break;
    case 'detect':
      run.region = e.region; run.centroid = e.centroid;
      placeBox();
      $('caseSub').textContent =
        `${run.mode} · ${e.centroid[1].toFixed(3)}°N ${e.centroid[0].toFixed(3)}°E · ` +
        `S2 ${run.windows.before.slice(0, 4)} → ${run.windows.after.slice(0, 4)}`;
      liveLog(`• Detected ${e.region.area_ha} ha of change`);
      setBeat(2);
      $('telemetry').classList.remove('pending');
      break;
    case 'classify':
      run.classification = e.classification;
      $('clsLabel').textContent = e.classification.label.replaceAll('_', ' ');
      liveLog(`• Classified: ${e.classification.label.replaceAll('_', ' ')} (${e.classification.source}${e.classification.confidence != null ? ', conf ' + e.classification.confidence : ''})`);
      if (e.second_opinion) {
        const v = { confirm: 'confirmed', downgrade: 'downgraded', reject: 'flagged likely-false' }[e.second_opinion.verdict] || e.second_opinion.verdict;
        liveLog(`• Second opinion: ${v}`, e.second_opinion.verdict !== 'confirm');
      }
      setBeat(3);
      break;
    case 'legality':
      run.flags = e.flags; run.severity = e.severity; run.overlays = e.overlays;
      buildOverlays(); renderSeverity();
      liveLog(e.flags.length ? `• Legality: ${e.flags.length} rule${e.flags.length > 1 ? 's' : ''} flagged` : '• Legality: no rule triggered', e.flags.length > 0);
      setBeat(4);
      break;
    case 'dossier':
      run.dossier = e.dossier;
      $('dossierLink').href = `runs/${runId}/${e.dossier}`;
      $('dossierLink').textContent = '▤ ' + e.dossier;
      liveLog('• Dossier compiled');
      setBeat(5);
      break;
    case 'done':
      $('stageLoading').hidden = true;
      run = e.run; runId = e.run.id;
      renderCaseMeta();
      liveLog('• Alert drafted — not sent', true);
      setupTimeseries();
      setBeat(6);
      liveMode = false;
      refreshManifest();
      break;
    case 'nochange':
      // Valid negative result — keep the before/after map visible; do NOT cover it with
      // the stage-msg overlay. Surface the verdict in the log + caption instead.
      liveMode = false;
      $('stageLoading').hidden = true;
      $('stageMsg').hidden = true;
      $('status').innerHTML = '<span class="dot"></span>NO CHANGE';
      $('caseTitle').textContent = run.title || $('caseTitle').textContent;
      $('caseSub').textContent =
        `${run.mode || 'scan'} · S2 ${(e.windows?.before || '').slice(0, 4)} → ${(e.windows?.after || '').slice(0, 4)} · no significant change`;
      liveLog('✓ ' + (e.message || 'No significant change detected.'));
      setBeat(1);   // perceive done (imagery shown); stop before reason/act
      break;
    case 'error':
      liveMode = false;
      $('stageLoading').hidden = true;
      $('stageMsg').textContent = e.message || 'No result for this zone.';
      $('stageMsg').hidden = false;
      $('status').innerHTML = '<span class="dot"></span>NO CHANGE';
      liveLog('⚠ ' + e.message, true);
      break;
  }
  // make the live wait legible: show what the agent is doing right now
  const STEP = { open: 'STARTING…', start: 'FETCHING SENTINEL-2…', imagery: 'DETECTING CHANGE…',
    detect: 'CLASSIFYING…', classify: 'CHECKING LEGALITY…', legality: 'COMPILING DOSSIER…',
    dossier: 'DRAFTING ALERT…' };
  if (liveMode && STEP[e.stage]) liveStatus(STEP[e.stage]);
}

async function refreshManifest() {
  const m = await fetch('/api/manifest').then(r => r.json()).catch(() => null);
  if (!m || !m.runs) return;
  manifest = m;
  // keep the picker + map pins in sync (a fresh 'live' site may have appeared)
  const picker = $('picker'), have = new Set([...picker.options].map(o => o.value));
  m.runs.forEach(r => {
    if (!have.has(r.id)) {
      const o = document.createElement('option'); o.value = r.id; o.textContent = r.title;
      picker.appendChild(o);
    }
  });
  if (runId) picker.value = runId;
  renderPins(false);
  renderAOIs();
  renderQueue();
}

async function loadRun(id) {
  stop();
  liveMode = false;
  $('stageLoading').hidden = true; $('stageMsg').hidden = true;
  $('telemetry').classList.remove('pending'); $('sevPanel').classList.remove('pending');
  runId = id;
  run = await fetch(`runs/${id}/run.json`).then(r => r.json());
  $('imgBefore').src = `runs/${id}/before.png`;
  $('imgAfter').src = `runs/${id}/after.png`;
  $('beforeTag').textContent = 'BEFORE'; $('afterTag').textContent = 'AFTER';
  placeBox();
  buildOverlays();
  $('ndvi').style.color = 'var(--red-t)';
  $('bsi').style.color = 'var(--amber)';
  $('clsLabel').textContent = run.classification.label.replaceAll('_', ' ');
  // telemetry numbers are filled (and counted up) per beat:
  ['ndvi', 'bsi', 'area'].forEach(k => $(k).textContent = '—');
  $('confText').textContent = '—';
  // evidence
  $('dossierLink').href = `runs/${id}/${run.dossier}`;
  $('dossierLink').textContent = '▤ ' + run.dossier;
  // reasoning trace — condensed; revealed all at once for a cached run
  const log = $('log'); log.innerHTML = '';
  condenseNarration(run).forEach(line => log.appendChild(logLine(line.text, line.flag)));
  revealReasoning();
  setupTimeseries();
  setBeat(0);
}

// Compact, scannable trace for the inline reasoning panel: one short line per step,
// no coordinates / sub-metrics. Derives from the run's structured fields (not the
// verbose run.narration), so cached + live runs read the same.
function condenseNarration(r) {
  const cls = r.classification || {};
  const lines = [
    { text: '• Pulled before/after imagery' },
    { text: r.region ? `• Detected ${r.region.area_ha} ha of change` : '• No significant change detected' },
  ];
  if (cls.label) {
    lines.push({ text: `• Classified: ${cls.label.replaceAll('_', ' ')} (${cls.source || 'heuristic'}${cls.confidence != null ? ', conf ' + cls.confidence : ''})` });
  }
  if (r.second_opinion) {
    const v = { confirm: 'confirmed', downgrade: 'downgraded', reject: 'flagged likely-false' }[r.second_opinion.verdict] || r.second_opinion.verdict;
    lines.push({ text: `• Second opinion: ${v}`, flag: r.second_opinion.verdict !== 'confirm' });
  }
  const nFlags = (r.flags || []).length;
  lines.push({ text: nFlags ? `• Legality: ${nFlags} rule${nFlags > 1 ? 's' : ''} flagged` : '• Legality: no rule triggered', flag: nFlags > 0 });
  lines.push({ text: '• Dossier compiled' });
  lines.push({ text: '• Alert drafted — not sent', flag: true });
  return lines;
}

// change box as % of the grid (shared by cached + live paths)
function placeBox() {
  if (!run.region || !run.images.grid) return;
  const g = run.images.grid, [r0, c0, r1, c1] = run.region.pixel_bbox, box = $('box');
  box.style.left = (c0 / g * 100) + '%';
  box.style.top = (r0 / g * 100) + '%';
  box.style.width = ((c1 - c0) / g * 100) + '%';
  box.style.height = ((r1 - r0) / g * 100) + '%';
  $('boxLbl').textContent = `${run.region.id} · ${run.region.area_ha} ha`;
}

// reference-layer boundaries the change crosses (protected / setback / permit / coast)
function buildOverlays() {
  const ov = $('overlays'); ov.innerHTML = '';
  (run.overlays || []).forEach(o => {
    const el = document.createElementNS('http://www.w3.org/2000/svg', o.kind === 'line' ? 'polyline' : 'polygon');
    el.setAttribute('points', o.points.map(p => p.join(',')).join(' '));
    el.setAttribute('class', o.type);
    ov.appendChild(el);
  });
}

function logLine(text, flag) {
  const d = document.createElement('div');
  const isFlag = flag !== undefined ? flag : /\bflag\b|outside|setback|protected/i.test(text);
  d.className = 'l' + (isFlag ? ' flag' : '');
  d.textContent = text;
  return d;
}

// --- time-series onset + scrubber -------------------------------------------
const _tsX = (i, n) => (n <= 1 ? 50 : i / (n - 1) * 100);
const _tsY = (a, max) => 30 - (a / max) * 26 - 2;

function setupTimeseries() {
  const ts = run.timeseries, el = $('ts');
  if (!ts || !ts.series || !ts.series.length) { el.hidden = true; return; }
  el.hidden = false;
  $('tsOnset').textContent = ts.onset ? `Expansion began ${ts.onset}` : 'no clear onset';
  const n = ts.series.length, max = Math.max(...ts.series.map(s => s.area_ha), 0.001);
  const pts = ts.series.map((s, i) => `${_tsX(i, n).toFixed(1)},${_tsY(s.area_ha, max).toFixed(1)}`).join(' ');
  const onsetIdx = ts.years.indexOf(ts.onset);
  let svg = onsetIdx >= 0
    ? `<line class="onset" x1="${_tsX(onsetIdx, n).toFixed(1)}" y1="0" x2="${_tsX(onsetIdx, n).toFixed(1)}" y2="30"/>` : '';
  svg += `<polyline class="area" points="0,30 ${pts} 100,30"/><polyline class="line" points="${pts}"/>`;
  ts.series.forEach((s, i) => { svg += `<circle class="dot" cx="${_tsX(i, n).toFixed(1)}" cy="${_tsY(s.area_ha, max).toFixed(1)}" r="1.1"/>`; });
  svg += `<circle class="marker" id="tsMarker" cx="0" cy="0" r="2.2"/>`;
  $('tsSpark').innerHTML = svg;

  const slider = $('tsSlider'), last = n - 1;
  slider.min = 0; slider.max = last; slider.value = last;
  slider.oninput = () => scrubYear(ts, +slider.value);
  scrubYear(ts, last);
}

function scrubYear(ts, idx) {
  const s = ts.series[idx], year = ts.years[idx];
  $('imgAfter').src = `runs/${runId}/${ts.images[String(year)]}`;
  $('afterTag').textContent = `AFTER · ${year}`;
  $('tsReadout').textContent = `${year} · ${s.area_ha} ha`;
  const n = ts.series.length, max = Math.max(...ts.series.map(x => x.area_ha), 0.001), mk = $('tsMarker');
  if (mk) { mk.setAttribute('cx', _tsX(idx, n).toFixed(1)); mk.setAttribute('cy', _tsY(s.area_ha, max).toFixed(1)); }
}

// --- Motion helpers (direct/no-op fallback when Motion didn't load) ---------
function num(el, to, fmt, doAnimate) {
  if (animate && doAnimate) animate(0, to, { duration: 0.9, ease: "easeOut", onUpdate: v => el.textContent = fmt(v) });
  else el.textContent = fmt(to);
}
function flourish(el, keyframes, options) { if (animate && el) animate(el, keyframes, options); }

function setBeat(n) {
  const prev = beat;
  beat = Math.max(0, Math.min(BEATS - 1, n));
  body.dataset.beat = beat;
  $('status').innerHTML = beat === 0 ? '<span class="dot"></span>READY'
    : (beat >= BEATS - 1 ? '<span class="dot"></span>COMPLETE' : '<span class="dot"></span>RUNNING');

  // step rail
  setPhase('perceive', beat >= 1, 'on', prev < 1);
  setPhase('reason', beat >= 2, 'warn', prev < 2);
  setPhase('act', beat >= 5, 'on', prev < 5);
  markStep('fetch', beat >= 1); markStep('align', beat >= 1);
  markStep('detect', beat >= 2); markStep('classify', beat >= 3); markStep('legality', beat >= 4);
  markStep('dossier', beat >= 5); markStep('alert', beat >= 6);

  // telemetry (from beat 2) — count up; pop the change box on first reveal
  if (run && beat >= 2) {
    const r = run.region, crossing = prev < 2;
    num($('ndvi'), Math.abs(r.ndvi_drop), v => '−' + v.toFixed(2), crossing);
    num($('bsi'), r.bsi_rise, v => '+' + v.toFixed(2), crossing);
    num($('area'), r.area_ha, v => v.toFixed(2) + ' ha', crossing);
    if (crossing) flourish($('box'), { scale: [0.5, 1] }, { duration: 0.6, ease: "backOut" });
  } else {
    ['ndvi', 'bsi', 'area'].forEach(k => $(k).textContent = '—');
  }

  // classification + confidence (from beat 3)
  if (run && beat >= 3) {
    const c = run.classification, crossing = prev < 3;
    num($('confText'), c.confidence, v => `confidence ${v.toFixed(2)} · ${c.source}`, crossing);
    if (crossing) flourish($('clsLabel'), { y: [10, 0] }, { duration: 0.5, ease: "easeOut" });
  } else {
    $('confText').textContent = '—';
  }
  $('confBar').style.width = beat >= 3 && run ? (run.classification.confidence * 100) + '%' : '0';

  if (run && beat >= 6 && prev < 6) flourish($('draft'), { y: [10, 0] }, { duration: 0.5, ease: "easeOut" });

  // reveal log lines up to current beat (live mode appends its own, already shown)
  if (!liveMode) {
    const lines = document.querySelectorAll('#log .l');
    const reveal = [0, 2, 3, 4, 5, 6, 7][beat];
    lines.forEach((l, i) => l.classList.toggle('show', i < reveal));
  }
}

function setPhase(name, active, cls, justActivated) {
  const el = document.querySelector(`.rail .ph[data-phase="${name}"]`);
  el.classList.toggle(cls, active);
  if (active && justActivated) flourish(el, { scale: [1, 1.08, 1] }, { duration: 0.4 });
}
function markStep(step, done) {
  const el = document.querySelector(`.rail .sub[data-step="${step}"]`);
  el.classList.toggle('done', done); el.classList.toggle('on', done);
}

function play() {
  if (!run) return;
  if (beat >= BEATS - 1) setBeat(0);
  playing = true;
  clearInterval(timer);
  timer = setInterval(() => {
    if (beat >= BEATS - 1) { stop(); return; }
    setBeat(beat + 1);
  }, BEAT_MS);
}
function stop() { playing = false; clearInterval(timer); timer = null; }

function onKey(e) {
  if (e.code === 'Escape') {
    if (!$('intro').hidden) { hideIntro(); return; }
    if ($('chat').classList.contains('open')) { $('chat').classList.remove('open'); return; }
    if (document.body.classList.contains('view-case')) { showOverview(); return; }
  }
  if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;  // don't hijack typing
  if (e.code === 'Space') { e.preventDefault(); playing ? stop() : play(); }
  else if (e.code === 'ArrowRight') { stop(); setBeat(beat + 1); }
  else if (e.code === 'ArrowLeft') { stop(); setBeat(beat - 1); }
}

function setupSwipe() {
  const stage = $('stage');
  let dragging = false;
  const move = (clientX) => {
    const rect = stage.getBoundingClientRect();
    const pct = Math.max(2, Math.min(98, (clientX - rect.left) / rect.width * 100));
    stage.style.setProperty('--swipe', pct + '%');
  };
  // grab ANYWHERE on the image; pointer-capture keeps the drag even past the edges,
  // and preventDefault stops the browser from selecting the image (the "turns blue" bug).
  stage.addEventListener('pointerdown', (e) => {
    dragging = true;
    try { stage.setPointerCapture(e.pointerId); } catch (_) {}
    move(e.clientX);
    e.preventDefault();
  });
  stage.addEventListener('pointermove', (e) => { if (dragging) { move(e.clientX); e.preventDefault(); } });
  const end = (e) => { dragging = false; try { stage.releasePointerCapture(e.pointerId); } catch (_) {} };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
}

init();
