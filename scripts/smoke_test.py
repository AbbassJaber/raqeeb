import json, urllib.request, urllib.error
B = 'http://127.0.0.1:8000'
def get(p): return urllib.request.urlopen(B + p, timeout=30)
def post(p, body):
    req = urllib.request.Request(B + p, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=180)
def stages(p, body):
    return [json.loads(l.decode()[5:].strip())['stage'] for l in post(p, body) if l.decode().startswith('data:')]

checks = []
h = get('/').read().decode()
checks.append(('GET /  (Run analysis + badge + hint + chat FAB)', all(s in h for s in ('Run analysis', 'liveBadge', 'queueHint', 'chatFab'))))
js = get('/app.js').read().decode()
checks.append(('GET /app.js  (key fns present)', all(s in js for s in ('refreshLiveBadge', 'runAgentic', 'renderAOIs', 'deleteCase'))))
checks.append(('GET /styles.css', get('/styles.css').status == 200))
m = json.load(get('/api/manifest')); checks.append(('/api/manifest (>=4 runs, has aoi_km2)', len(m['runs']) >= 4 and 'aoi_km2' in m['runs'][0]))
r = json.load(get('/api/reference')); checks.append(('/api/reference (3 layers)', all(k in r for k in ('protected', 'permitted', 'coastline'))))
hl = json.load(get('/api/health')); checks.append(('/api/health', 'offline' in hl))
c = json.load(post('/api/chat', {'question': 'what is the worst candidate?', 'history': []})); checks.append(('/api/chat answer', bool(c.get('answer')) and bool(c.get('cases'))))
sc = json.load(post('/api/chat', {'question': 'scan the coast at Chekka'})); checks.append(('/api/chat scan-intent', sc.get('action', {}).get('type') == 'scan'))
checks.append(('/api/run SSE -> done', set(['done', 'end']) <= set(stages('/api/run', {'preset': 'quarry-demo'}))))
checks.append(('/api/agent-run SSE -> done (offline fallback)', 'done' in stages('/api/agent-run', {'preset': 'quarry-demo'})))
try:
    post('/api/alert', {'id': 'quarry-demo', 'reviewed': False}); gate = False
except urllib.error.HTTPError as ex:
    gate = ex.code == 403
checks.append(('/api/alert refuses without review (403 gate)', gate))
a = json.load(post('/api/alert', {'id': 'quarry-demo', 'reviewed': True})); checks.append(('/api/alert prepares when reviewed', a.get('ok') is True))
try:
    post('/api/run', {'bbox': [35.0, 33.5, 35.6, 34.1]}); big = False
except urllib.error.HTTPError as ex:
    big = ex.code == 422
checks.append(('/api/run rejects oversized zone (422)', big))
try:
    req = urllib.request.Request(B + '/api/run/__none__', method='DELETE'); urllib.request.urlopen(req, timeout=10); dele = False
except urllib.error.HTTPError as ex:
    dele = ex.code == 404   # route exists, correctly 404s on a missing case (non-destructive check)
checks.append(('DELETE /api/run/{id} route (404 on missing)', dele))
post('/api/review', {'id': 'ain-dara', 'status': 'cleared'})
set_ok = {r['id']: r.get('review') for r in json.load(get('/api/manifest'))['runs']}.get('ain-dara') == 'cleared'
post('/api/review', {'id': 'ain-dara', 'status': 'pending'})
reset_ok = {r['id']: r.get('review') for r in json.load(get('/api/manifest'))['runs']}.get('ain-dara') is None
checks.append(('/api/review set+reset onsite disposition', set_ok and reset_ok))

print('\n'.join(('PASS  ' if p else 'FAIL  ') + n for n, p in checks))
print('\n' + ('ALL PASS' if all(p for _, p in checks) else 'SOME FAILED'))
