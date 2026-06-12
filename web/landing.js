/* Raqeeb landing — scroll reveals, count-ups, the before/after swipe, and an optional
   Motion parallax flourish. No build step; Motion is a progressive enhancement loaded from
   the same CDN app.js uses, with full CSS/IO fallbacks so the page never depends on it. */

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ── scroll reveals + section "in" state ──────────────────── */
function setupReveals() {
  const targets = $$('.reveal, .loop, .scale-map, .sev, .scope-frame');
  if (reduced || !('IntersectionObserver' in window)) {
    targets.forEach(el => el.classList.add('in'));
    targets.forEach(maybeCount);
    revealAnno($('.scope-frame'), true);
    return;
  }
  // stagger siblings within a band by setting a transition-delay per index
  $$('.stats, .how-grid, .pledge, .hero-cta').forEach(group => {
    $$('.reveal', group).forEach((el, i) => { el.style.transitionDelay = `${i * 90}ms`; });
  });
  const io = new IntersectionObserver((entries, obs) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add('in');
      maybeCount(e.target);
      if (e.target.classList.contains('scope-frame')) revealAnno(e.target, false);
      obs.unobserve(e.target);
    }
  }, { threshold: 0.18, rootMargin: '0px 0px -8% 0px' });
  targets.forEach(el => io.observe(el));
}

/* ── number count-ups ─────────────────────────────────────── */
function maybeCount(scope) {
  $$('.stat-num[data-count]', scope).forEach(el => {
    if (el.dataset.done) return;
    el.dataset.done = '1';
    countTo(el, +el.dataset.count, el.dataset.suffix || '');
  });
}
function countTo(el, target, suffix) {
  const fmt = n => Math.round(n).toLocaleString('en-US') + suffix;
  if (reduced || target === 0) { el.textContent = fmt(target); return; }
  const dur = 1200, t0 = performance.now();
  const tick = now => {
    const p = Math.min(1, (now - t0) / dur);
    const eased = 1 - Math.pow(1 - p, 3);            // easeOutCubic
    el.textContent = fmt(target * eased);
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ── hero before/after swipe ──────────────────────────────── */
function setupSwipe() {
  const frame = $('.scope-frame'); if (!frame) return;
  let dragging = false;
  const move = clientX => {
    const r = frame.getBoundingClientRect();
    const pct = Math.max(4, Math.min(96, ((clientX - r.left) / r.width) * 100));
    frame.style.setProperty('--swipe', pct + '%');
  };
  frame.addEventListener('pointerdown', e => {
    dragging = true;
    try { frame.setPointerCapture(e.pointerId); } catch (_) {}
    move(e.clientX); e.preventDefault();
  });
  frame.addEventListener('pointermove', e => { if (dragging) { move(e.clientX); e.preventDefault(); } });
  const end = e => { dragging = false; try { frame.releasePointerCapture(e.pointerId); } catch (_) {} };
  frame.addEventListener('pointerup', end);
  frame.addEventListener('pointercancel', end);
  // a one-time "nudge" so visitors notice it's draggable
  if (!reduced) {
    frame.animate?.([{ '--swipe': '52%' }], { duration: 0 });
    setTimeout(() => {
      frame.style.transition = 'none';
      let x = 52; const swing = [52, 40, 64, 52];
      swing.forEach((v, i) => setTimeout(() => frame.style.setProperty('--swipe', v + '%'), 600 + i * 280));
    }, 400);
  }
}

/* ── annotation lines (shoreline + setback) draw-in ───────── */
function revealAnno(frame, instant) {
  if (!frame) return;
  const els = $$('.scope-anno polyline, .anno-lbl', frame);
  els.forEach((el, i) => {
    if (reduced || instant) { el.style.opacity = ''; return; }
    el.style.opacity = '0';
    el.style.transition = `opacity .8s var(--ease) ${0.35 + i * 0.12}s`;
    requestAnimationFrame(() => requestAnimationFrame(() => { el.style.opacity = ''; }));
  });
}

/* ── optional Motion parallax (graceful if CDN is unreachable) ── */
async function setupParallax() {
  if (reduced) return;
  try {
    const { scroll, animate } = await import('https://cdn.jsdelivr.net/npm/motion@11.13.5/+esm');
    const stars = $('.stars'), scope = $('.scope');
    if (stars) scroll(animate(stars, { y: [0, 120] }, { ease: 'linear' }));
    if (scope) scroll(animate(scope, { y: [40, -40] }, { ease: 'linear' }),
                      { target: scope, offset: ['start end', 'end start'] });
  } catch (_) { /* CSS-only is fine */ }
}

setupReveals();
setupSwipe();
setupParallax();
