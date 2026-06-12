// Bilingual (English / Arabic) layer for the watchroom.
//
// One flat dictionary keyed by short ids. `t(key, vars)` looks up the current locale
// (falling back to English, then to the key itself). `applyLocale()` sets <html dir/lang>,
// fills every [data-i18n] element, and lets app.js re-render its dynamic views.
//
// Locale persists in localStorage. The map tiles + satellite stage stay LTR — only the
// surrounding chrome flips to RTL — see the [dir="rtl"] rules in styles.css.

const I18N = {
  en: {
    // header
    'brand.kicker': 'Environmental monitoring · Lebanon',
    'btn.watchroom': '◰ Watchroom',
    'btn.run': '⚡ Run analysis',
    'btn.run.title': 'Run the agent live on this site, step by step',
    'btn.watchroom.title': 'Back to the map',
    'btn.help.title': 'What is this?',
    'lang.toggle': 'عربي',
    'lang.toggle.title': 'التبديل إلى العربية',
    'status.watching': 'WATCHING',
    'status.ready': 'READY',
    'status.running': 'RUNNING',
    'status.complete': 'COMPLETE',
    'status.noserver': 'NO SERVER',
    'status.blocked': 'BLOCKED',
    'status.nochange': 'NO CHANGE',
    // live step status
    'step.starting': 'STARTING…',
    'step.fetching': 'FETCHING SENTINEL-2…',
    'step.detecting': 'DETECTING CHANGE…',
    'step.classifying': 'CLASSIFYING…',
    'step.legality': 'CHECKING LEGALITY…',
    'step.dossier': 'COMPILING DOSSIER…',
    'step.alert': 'DRAFTING ALERT…',
    // queue
    'queue.candidates': 'Candidates',
    'queue.hint': 'Click a site to inspect it · or draw a box (▢ on the map) / ask Raqeeb to scan a new area.',
    'queue.scan': '＋ Scan a new area',
    'queue.foot': 'Each is a candidate for human verification — never an accusation. Boundaries are proxies.',
    'queue.empty': 'No candidates yet. Draw a zone on the map (▢ top-left) or ask Raqeeb to scan one.',
    'queue.eval.title': 'Measured accuracy on a labelled real-site set',
    'eval.validated': 'Validated',
    'eval.on': 'on {n} real sites',
    'queue.unscored': 'unscored',
    'queue.cleared': 'cleared',
    'queue.watching': 'watching ~{km} km²',
    'queue.lastsweep': 'last sweep {date}',
    // map
    'sev.title': 'Severity',
    'sev.critical': 'critical',
    'sev.high': 'high',
    'sev.medium': 'medium',
    'sev.low': 'low',
    'sev.unscored': 'unscored',
    'pop.open': '▶ open dossier',
    'map.caption': 'Click a pin or a card · draw a <b>2–3 km</b> box (▢ top-left) to scan a new zone live.',
    'map.layer.candidates': 'Candidates',
    'map.layer.areas': 'Monitored areas',
    'map.layer.coastline': 'Coastline (national boundary)',
    'map.layer.protected': 'Protected areas (WDPA)',
    'map.layer.permitted': 'Permitted zones (proxy)',
    // step rail
    'rail.perceive': 'Perceive',
    'rail.fetch': 'fetch imagery',
    'rail.align': 'align composites',
    'rail.reason': 'Reason',
    'rail.detect': 'detect change',
    'rail.classify': 'classify',
    'rail.legality': 'check legality',
    'rail.act': 'Act',
    'rail.dossier': 'compile dossier',
    'rail.alert': 'draft alert',
    // telemetry
    'tel.title': 'Telemetry',
    'tel.area': 'Area',
    'stage.before': 'BEFORE',
    'stage.after': 'AFTER',
    'stage.legend': '10 m · EPSG:32636 geometry · cloud-masked composite',
    'stage.loading': 'analysing imagery…',
    'stage.scanning': 'Scanning…',
    // side panels
    'ts.title': 'Onset · change over time',
    'ts.onset': 'Expansion began {year}',
    'ts.noonset': 'no clear onset',
    'panel.reasoning': '✦ Agent reasoning',
    'panel.review': 'Review & act',
    'file.dossier': '▤ dossier',
    'draft.notsent': '✉ Alert drafted — not sent',
    'review.check': 'I have reviewed this candidate against official records.',
    'review.prepare': 'Prepare alert for reviewer',
    'review.preparing': 'preparing…',
    'fr.head': 'After the team checks onsite',
    'fr.clear': '✓ Verified normal',
    'fr.confirm': '⚠ Confirmed',
    'fr.notchecked': 'Not yet field-checked.',
    'fr.cleared': 'Verified normal — cleared',
    'fr.confirmed': 'Confirmed violation',
    'fr.savefail': 'Could not save — is the server running?',
    'disclaimer': 'Candidate for human verification — not a legal determination. Boundaries are proxies; confirm against official records.',
    // chat
    'chat.title': '✦ Ask Raqeeb',
    'chat.q1': 'What needs my attention?',
    'chat.q2': 'How many are critical?',
    'chat.q3': 'Anything on the coast near Beirut?',
    'chat.q4': 'Summarize the Bourj Hammoud case.',
    'chat.placeholder': 'Ask about the findings…',
    'chat.foot': 'Grounded in current candidates — for human review, never an accusation.',
    'chat.fab.title': 'Ask Raqeeb AI',
    'chat.thinking': 'thinking…',
    'chat.noanswer': '(no answer)',
    'chat.runscan': '▶ Run this scan',
    'chat.noserver': 'The server isn’t running — start scripts/run_server.py.',
    // intro
    'intro.kicker': 'Environmental monitoring · Lebanon',
    'intro.title': '<b>RAQEEB</b> watches Lebanon from space',
    'intro.lede': 'An AI agent scans Sentinel-2 satellite imagery for likely environmental violations — illegal quarrying and coastal encroachment — and reasons about whether each change breaks a rule.',
    'intro.step1': '<b>Pick a candidate</b> on the map or list — or draw a box / ask Raqeeb to scan a new area.',
    'intro.step2': '<b>Watch the agent analyze it</b> live: detect change → classify with vision → check the law.',
    'intro.step3': '<b>Review the evidence</b> and prepare an alert for a human reviewer.',
    'intro.note': 'Every result is a <b>candidate for human verification — never an accusation</b>. Boundaries are proxies; alerts are drafted for a person to send, never automatically.',
    'intro.start': 'Enter the watchroom →',
    // live badge
    'badge.demo': '○ Demo mode · synthetic pipeline',
    'badge.live': '● Live · Sentinel-2 + ',
    // change classes (classification label)
    'cls.quarry_expansion': 'quarry expansion',
    'cls.coastal_construction': 'coastal construction',
    'cls.building': 'building',
    'cls.agriculture': 'agriculture',
    'cls.natural': 'natural',
    // reasoning trace (condensed)
    'trace.imagery': '• Pulled before/after imagery',
    'trace.nochange': '• No significant change detected',
    'trace.detected': '• Detected {area} ha of change',
    'trace.classified': '• Classified: {label} ({source}{conf})',
    'trace.second': '• Second opinion: {verdict}',
    'trace.legality.flagged': '• Legality: {n} rule{s} flagged',
    'trace.legality.none': '• Legality: no rule triggered',
    'trace.dossier': '• Dossier compiled',
    'trace.alert': '• Alert drafted — not sent',
    'verdict.confirm': 'confirmed',
    'verdict.downgrade': 'downgraded',
    'verdict.reject': 'flagged likely-false',
    'nochange.line': 'No significant change detected.',
    'nochange.sub': 'no significant change',
    // misc + dialogs
    'flagged': 'flagged',
    'rules': 'rules',
    'rule': 'rule',
    'confirm.delete': 'Remove "{title}" from the queue? This deletes its cached analysis.',
    'alert.deletefail': 'Could not delete — is the server running?',
    'live.noserver': 'Live runs need the server — run scripts/run_server.py.',
    'run.rejected': 'run rejected',
    'live.servermsg': 'live runs need the server — python scripts/run_server.py',
    'alert.couldnot': 'could not prepare alert',
    // case facts strip
    'fact.cleared': '✓ verified normal (cleared)',
    'fact.confirmed': '⚠ confirmed onsite',
    'fact.2nd': '{mark} 2nd opinion: {v}',
    'fact.insea': 'in the sea / at the shore',
    'fact.fromcoast': '{m} m from coast',
    'fact.confidence': '◴ confidence {conf} · {source}',
    'basis.setback': 'Maritime public domain · 150 m setback',
    'basis.protected': 'Protected-area boundary',
    'basis.permit': 'Outside any permitted quarry zone',
    'verdict2.confirm': 'confirmed',
    'verdict2.downgrade': 'downgraded',
    'verdict2.reject': 'likely false',
    // severity-factor labels (backend emits English; translated on render)
    'sevf.setback': 'within the coastal public-domain setback',
    'sevf.permit': 'quarry-like change outside any permitted zone',
    'sevf.protected': 'overlaps a protected area',
    'sevf.protected_named': 'overlaps {name} (protected area)',
    'sevf.area': 'change area {n} ha',
    'sevf.signal': 'signal strength (NDVI {ndvi}, BSI {bsi})',
    'sevf.confidence': 'classifier confidence {n}',
  },

  ar: {
    'brand.kicker': 'المراقبة البيئية · لبنان',
    'btn.watchroom': '◰ غرفة المراقبة',
    'btn.run': '⚡ تشغيل التحليل',
    'btn.run.title': 'تشغيل الوكيل مباشرةً على هذا الموقع، خطوة بخطوة',
    'btn.watchroom.title': 'العودة إلى الخريطة',
    'btn.help.title': 'ما هذا؟',
    'lang.toggle': 'EN',
    'lang.toggle.title': 'Switch to English',
    'status.watching': 'مراقبة',
    'status.ready': 'جاهز',
    'status.running': 'قيد التشغيل',
    'status.complete': 'اكتمل',
    'status.noserver': 'لا يوجد خادم',
    'status.blocked': 'محظور',
    'status.nochange': 'لا تغيير',
    'step.starting': 'البدء…',
    'step.fetching': 'جلب صور سنتينل-2…',
    'step.detecting': 'كشف التغيّر…',
    'step.classifying': 'التصنيف…',
    'step.legality': 'فحص القانونية…',
    'step.dossier': 'تجميع الملف…',
    'step.alert': 'صياغة التنبيه…',
    'queue.candidates': 'المرشّحون',
    'queue.hint': 'انقر على موقع لفحصه · أو ارسم مربّعاً (▢ على الخريطة) / اطلب من رقيب مسح منطقة جديدة.',
    'queue.scan': '＋ مسح منطقة جديدة',
    'queue.foot': 'كل حالة هي مرشّح للتحقق البشري — وليست اتهاماً. الحدود تقريبية.',
    'queue.empty': 'لا مرشّحين بعد. ارسم منطقة على الخريطة (▢ أعلى اليسار) أو اطلب من رقيب مسحها.',
    'queue.eval.title': 'الدقة المُقاسة على مجموعة مواقع حقيقية موسومة',
    'eval.validated': 'مُتحقَّق',
    'eval.on': 'على {n} موقع حقيقي',
    'queue.unscored': 'غير مُقيّمة',
    'queue.cleared': 'مُبرَّأة',
    'queue.watching': 'مراقبة ~{km} كم²',
    'queue.lastsweep': 'آخر مسح {date}',
    'sev.title': 'الخطورة',
    'sev.critical': 'حرجة',
    'sev.high': 'عالية',
    'sev.medium': 'متوسطة',
    'sev.low': 'منخفضة',
    'sev.unscored': 'غير مُقيّمة',
    'pop.open': '▶ فتح الملف',
    'map.caption': 'انقر على دبّوس أو بطاقة · ارسم مربّعاً <b>٢–٣ كم</b> (▢ أعلى اليسار) لمسح منطقة جديدة مباشرةً.',
    'map.layer.candidates': 'المرشّحون',
    'map.layer.areas': 'المناطق المراقَبة',
    'map.layer.coastline': 'الخط الساحلي (الحدود الوطنية)',
    'map.layer.protected': 'المناطق المحميّة (WDPA)',
    'map.layer.permitted': 'المناطق المرخّصة (تقريبي)',
    'rail.perceive': 'الإدراك',
    'rail.fetch': 'جلب الصور',
    'rail.align': 'محاذاة المركّبات',
    'rail.reason': 'الاستدلال',
    'rail.detect': 'كشف التغيّر',
    'rail.classify': 'التصنيف',
    'rail.legality': 'فحص القانونية',
    'rail.act': 'التصرّف',
    'rail.dossier': 'تجميع الملف',
    'rail.alert': 'صياغة التنبيه',
    'tel.title': 'القياسات',
    'tel.area': 'المساحة',
    'stage.before': 'قبل',
    'stage.after': 'بعد',
    'stage.legend': '١٠ م · إسقاط EPSG:32636 · مركّب خالٍ من الغيوم',
    'stage.loading': 'تحليل الصور…',
    'stage.scanning': 'جارٍ المسح…',
    'ts.title': 'البداية · التغيّر عبر الزمن',
    'ts.onset': 'بدأ التوسّع عام {year}',
    'ts.noonset': 'لا بداية واضحة',
    'panel.reasoning': '✦ استدلال الوكيل',
    'panel.review': 'المراجعة والإجراء',
    'file.dossier': '▤ الملف',
    'draft.notsent': '✉ تمّت صياغة التنبيه — لم يُرسَل',
    'review.check': 'لقد راجعتُ هذا المرشّح مقابل السجلات الرسمية.',
    'review.prepare': 'تجهيز التنبيه للمراجِع',
    'review.preparing': 'جارٍ التجهيز…',
    'fr.head': 'بعد تحقّق الفريق ميدانياً',
    'fr.clear': '✓ تحقّق سليم',
    'fr.confirm': '⚠ مؤكّد',
    'fr.notchecked': 'لم يُفحَص ميدانياً بعد.',
    'fr.cleared': 'تحقّق سليم — تمّت التبرئة',
    'fr.confirmed': 'مخالفة مؤكّدة',
    'fr.savefail': 'تعذّر الحفظ — هل الخادم يعمل؟',
    'disclaimer': 'مرشّح للتحقق البشري — ليس قراراً قانونياً. الحدود تقريبية؛ تحقّق مقابل السجلات الرسمية.',
    'chat.title': '✦ اسأل رقيب',
    'chat.q1': 'ما الذي يستدعي انتباهي؟',
    'chat.q2': 'كم عدد الحالات الحرجة؟',
    'chat.q3': 'هل من شيء على الساحل قرب بيروت؟',
    'chat.q4': 'لخّص حالة برج حمّود.',
    'chat.placeholder': 'اسأل عن النتائج…',
    'chat.foot': 'مبني على المرشّحين الحاليين — للمراجعة البشرية، وليس اتهاماً.',
    'chat.fab.title': 'اسأل رقيب الذكي',
    'chat.thinking': 'جارٍ التفكير…',
    'chat.noanswer': '(لا إجابة)',
    'chat.runscan': '▶ تشغيل هذا المسح',
    'chat.noserver': 'الخادم لا يعمل — شغّل scripts/run_server.py.',
    'intro.kicker': 'المراقبة البيئية · لبنان',
    'intro.title': '<b>رقيب</b> يراقب لبنان من الفضاء',
    'intro.lede': 'وكيل ذكاء اصطناعي يفحص صور سنتينل-2 بحثاً عن مخالفات بيئية محتملة — المقالع غير القانونية والتعدّي على الساحل — ويستدلّ على ما إذا كان كل تغيّر يخالف قاعدة.',
    'intro.step1': '<b>اختر مرشّحاً</b> على الخريطة أو القائمة — أو ارسم مربّعاً / اطلب من رقيب مسح منطقة جديدة.',
    'intro.step2': '<b>شاهد الوكيل يحلّله</b> مباشرةً: كشف التغيّر ← التصنيف بالرؤية ← فحص القانون.',
    'intro.step3': '<b>راجع الأدلّة</b> وجهّز تنبيهاً لمراجِع بشري.',
    'intro.note': 'كل نتيجة هي <b>مرشّح للتحقق البشري — وليست اتهاماً</b>. الحدود تقريبية؛ التنبيهات تُصاغ ليرسلها شخص، لا تلقائياً.',
    'intro.start': '← ادخل غرفة المراقبة',
    'badge.demo': '○ وضع العرض · خطّ أنابيب اصطناعي',
    'badge.live': '● مباشر · سنتينل-2 + ',
    'cls.quarry_expansion': 'توسّع محجر',
    'cls.coastal_construction': 'بناء ساحلي',
    'cls.building': 'مبنى',
    'cls.agriculture': 'زراعة',
    'cls.natural': 'طبيعي',
    'trace.imagery': '• تمّ جلب صور قبل/بعد',
    'trace.nochange': '• لم يُكتشَف تغيّر يُذكر',
    'trace.detected': '• كُشف تغيّر بمساحة {area} هكتار',
    'trace.classified': '• التصنيف: {label} ({source}{conf})',
    'trace.second': '• رأي ثانٍ: {verdict}',
    'trace.legality.flagged': '• القانونية: {n} قاعدة مُشار إليها',
    'trace.legality.none': '• القانونية: لم تُخالَف أي قاعدة',
    'trace.dossier': '• تمّ تجميع الملف',
    'trace.alert': '• تمّت صياغة التنبيه — لم يُرسَل',
    'verdict.confirm': 'مؤكّد',
    'verdict.downgrade': 'مُخفَّض',
    'verdict.reject': 'مُرجَّح أنه خاطئ',
    'nochange.line': 'لم يُكتشَف تغيّر يُذكر.',
    'nochange.sub': 'لا تغيّر يُذكر',
    'flagged': 'مُشار إليها',
    'rules': 'قواعد',
    'rule': 'قاعدة',
    'confirm.delete': 'إزالة "{title}" من القائمة؟ سيؤدي ذلك إلى حذف تحليلها المخزَّن.',
    'alert.deletefail': 'تعذّر الحذف — هل الخادم يعمل؟',
    'live.noserver': 'التشغيل المباشر يتطلّب الخادم — شغّل scripts/run_server.py.',
    'run.rejected': 'رُفض التشغيل',
    'live.servermsg': 'التشغيل المباشر يتطلّب الخادم — python scripts/run_server.py',
    'alert.couldnot': 'تعذّر تجهيز التنبيه',
    'fact.cleared': '✓ تحقّق سليم (مُبرَّأة)',
    'fact.confirmed': '⚠ مؤكّدة ميدانياً',
    'fact.2nd': '{mark} رأي ثانٍ: {v}',
    'fact.insea': 'في البحر / عند الشاطئ',
    'fact.fromcoast': '{m} م من الساحل',
    'fact.confidence': '◴ الثقة {conf} · {source}',
    'basis.setback': 'الأملاك العامة البحرية · مسافة ١٥٠ م',
    'basis.protected': 'حدود منطقة محميّة',
    'basis.permit': 'خارج أي منطقة محاجر مرخّصة',
    'verdict2.confirm': 'مؤكّد',
    'verdict2.downgrade': 'مُخفَّض',
    'verdict2.reject': 'مُرجَّح خاطئ',
    'sevf.setback': 'ضمن الأملاك العامة البحرية الساحلية',
    'sevf.permit': 'تغيّر شبيه بالمحاجر خارج أي منطقة مرخّصة',
    'sevf.protected': 'يتداخل مع منطقة محميّة',
    'sevf.protected_named': 'يتداخل مع {name} (منطقة محميّة)',
    'sevf.area': 'مساحة التغيّر {n} هكتار',
    'sevf.signal': 'قوة الإشارة (NDVI {ndvi}، BSI {bsi})',
    'sevf.confidence': 'ثقة المُصنِّف {n}',
  },
};

let _locale = 'en';

function _initLocale() {
  try { _locale = localStorage.getItem('rqLocale') || 'en'; } catch (_) { _locale = 'en'; }
  if (_locale !== 'ar') _locale = 'en';
  return _locale;
}

function getLocale() { return _locale; }

// t(key, vars) — current-locale string with {placeholder} interpolation; falls back
// to English then to the raw key, so a missing Arabic entry degrades gracefully.
function t(key, vars) {
  let s = (I18N[_locale] && I18N[_locale][key]);
  if (s == null) s = (I18N.en[key] != null ? I18N.en[key] : key);
  if (vars) for (const k in vars) s = s.replaceAll('{' + k + '}', vars[k]);
  return s;
}

function _applyStatic(root) {
  root = root || document;
  root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-html]').forEach(el => { el.innerHTML = t(el.dataset.i18nHtml); });
  root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
  root.querySelectorAll('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
  root.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
}

// Set <html dir/lang>, fill static strings, then call onApply so app.js re-renders
// dynamic views (queue, case meta, reasoning, status) in the new language.
function applyLocale(onApply) {
  document.documentElement.lang = _locale;
  document.documentElement.dir = _locale === 'ar' ? 'rtl' : 'ltr';
  document.body.classList.toggle('rtl', _locale === 'ar');
  _applyStatic();
  if (typeof onApply === 'function') onApply();
}

function setLocale(loc, onApply) {
  _locale = (loc === 'ar') ? 'ar' : 'en';
  try { localStorage.setItem('rqLocale', _locale); } catch (_) {}
  applyLocale(onApply);
}

function toggleLocale(onApply) { setLocale(_locale === 'ar' ? 'en' : 'ar', onApply); }

_initLocale();
window.i18n = { t, getLocale, setLocale, toggleLocale, applyLocale };
