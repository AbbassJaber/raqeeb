"""FastAPI backend for the cinematic player.

Serves the static player AND runs the real agent pipeline on demand, streaming each
stage to the browser over Server-Sent Events so the 'perceive -> reason -> act' beats
are driven by an *actual* run: live Sentinel-2 + Gemini when RAQEEB_OFFLINE=0, or the
synthetic pipeline (still executed live, with real timing) otherwise — so the demo
never fails on stage.

Run:  ./.venv/Scripts/python.exe scripts/run_server.py   # http://127.0.0.1:8000
"""
import json
import math
import queue
import shutil
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from raqeeb import config, democache, alert, agent, classify, legality, severity
from raqeeb.models import ChangeRegion, Classification, Finding

WEB = config.ROOT / "web"
RUNS = WEB / "runs"

app = FastAPI(title="Raqeeb · cinematic player")


class RunRequest(BaseModel):
    preset: str | None = None                 # re-run a known scenario by id
    bbox: list[float] | None = None           # or a drawn zone: [west, south, east, north]
    mode: str = "quarry"                       # "quarry" | "coastal"
    # Last ~6 years, same-season (summer): 2025 is the latest COMPLETE summer composite
    # (2026 summer isn't over yet, so live Sentinel-2 has no full 2026 May–Sep window).
    before_window: str = "2020-05-01..2020-09-30"
    after_window: str = "2025-05-01..2025-09-30"
    grid: int = 256
    title: str | None = None


@app.get("/api/health")
def health():
    """What the live path will actually do, so the UI can label real vs synthetic."""
    return {"offline": config.OFFLINE, "provider": config.LLM_PROVIDER,
            "ee_project": config.EE_PROJECT}


@app.get("/api/eval")
def eval_report():
    """Latest accuracy-harness report (precision/recall/F1 over the labelled set), so the
    watchroom can show a real, measured validation number. Absent until run_eval has run."""
    f = config.ROOT / "data" / "eval_report.json"
    if not f.exists():
        return JSONResponse({"available": False})
    rep = json.loads(f.read_text(encoding="utf-8"))
    o = rep.get("metrics", {}).get("overall", {})
    return JSONResponse({
        "available": True,
        "mode": rep.get("mode"), "classifier": rep.get("classifier"),
        "generated_at": rep.get("generated_at"),
        "n": o.get("n"), "tp": o.get("tp"), "fp": o.get("fp"),
        "fn": o.get("fn"), "tn": o.get("tn"),
        "precision": o.get("precision"), "recall": o.get("recall"),
        "f1": o.get("f1"), "accuracy": o.get("accuracy"),
        "by_mode": {k: v for k, v in rep.get("metrics", {}).items() if k != "overall"},
        "note": rep.get("note"),
    })


@app.get("/api/manifest")
def manifest():
    f = RUNS / "manifest.json"
    return JSONResponse(json.loads(f.read_text()) if f.exists()
                        else {"runs": [], "default": None})


@app.delete("/api/run/{run_id}")
def delete_run(run_id: str):
    """Remove a cached case (the operator curating the queue)."""
    if not run_id or any(c in run_id for c in ("/", "\\", "..")):
        raise HTTPException(400, "invalid id")
    d = RUNS / run_id
    if not (d.exists() and (d / "run.json").exists()):
        raise HTTPException(404, "no such case")
    shutil.rmtree(d, ignore_errors=True)
    democache.update_manifest(RUNS)
    return {"ok": True, "id": run_id}


class ReviewRequest(BaseModel):
    id: str
    status: str            # 'pending' | 'cleared' | 'confirmed'
    note: str | None = None


@app.post("/api/review")
def set_review(req: ReviewRequest):
    """Record the field team's onsite verdict on a candidate: cleared (verified normal),
    confirmed (a real violation), or pending (reset). Closes the human-in-the-loop."""
    if req.status not in ("pending", "cleared", "confirmed"):
        raise HTTPException(422, "status must be pending | cleared | confirmed")
    f = RUNS / req.id / "run.json"
    if not f.exists():
        raise HTTPException(404, "no such case")
    run = json.loads(f.read_text())
    if req.status == "pending":
        run.pop("field_review", None)
    else:
        run["field_review"] = {"status": req.status, "note": (req.note or "").strip(),
                               "at": datetime.now().isoformat(timespec="seconds")}
    f.write_text(json.dumps(run, indent=2))
    democache.update_manifest(RUNS)
    return {"ok": True, "status": req.status, "review": run.get("field_review")}


@app.get("/api/reference")
def reference():
    """Reference context layers (WGS84 GeoJSON) for the map: protected areas are the real
    WDPA layer and the coastline is the real national boundary; the permit layer is still a
    synthetic proxy (clearly labelled in the UI). Read as UTF-8 (reserve names are Arabic)."""
    out = {}
    for key, fn in (("protected", "protected_areas.geojson"),
                    ("permitted", "permitted_quarries.geojson"),
                    ("coastline", "coastline.geojson")):
        p = config.REFERENCE_DIR / fn
        if p.exists():
            out[key] = json.loads(p.read_text(encoding="utf-8"))
    return JSONResponse(out)


def _scenario(req: RunRequest) -> dict:
    """A preset id -> the cached scenario; a drawn bbox -> an ad-hoc 'live' scenario."""
    if req.preset:
        if req.preset not in democache.SCENARIOS:
            raise HTTPException(404, f"unknown preset '{req.preset}'")
        return democache.SCENARIOS[req.preset]
    if not req.bbox or len(req.bbox) != 4:
        raise HTTPException(422, "provide a preset or a 4-element bbox [w,s,e,n]")
    w, s, e, n = req.bbox
    cy, cx = (s + n) / 2, (w + e) / 2
    # how big is this on the ground? keep ~PIXEL_M resolution, and refuse oversized zones.
    width_m = abs(e - w) * 111_000 * math.cos(math.radians(cy))
    height_m = abs(n - s) * 111_000
    side_m = max(width_m, height_m)
    if side_m > config.SCAN_MAX_KM * 1000:
        raise HTTPException(422, f"Zone too large (~{side_m / 1000:.1f} km across). Draw "
                                 f"≤ {config.SCAN_MAX_KM:g} km so detection stays at ~{config.PIXEL_M} m/pixel.")
    grid = max(config.SCAN_GRID_MIN, min(config.SCAN_GRID_MAX, round(side_m / config.PIXEL_M)))
    title = req.title or f"Drawn zone · {cy:.3f}N {cx:.3f}E"
    return {"id": "live", "title": title, "name": title, "mode": req.mode,
            "bbox": (w, s, e, n), "before_window": req.before_window,
            "after_window": req.after_window, "grid": grid,
            "nearest_place": title}


@app.post("/api/run")
def run(req: RunRequest):
    """Run the pipeline in a worker thread; stream each stage out as it completes."""
    scenario = _scenario(req)
    q: "queue.Queue" = queue.Queue()

    def cb(stage, payload):
        q.put({"stage": stage, **payload})

    def worker():
        try:
            democache.build_run(scenario, out_root=RUNS, use_llm=True, on_step=cb)
        except democache.NoChangeDetected:
            pass  # build_run already emitted "nochange" (map stays visible); not an error
        except Exception as exc:  # surface to the client as a stream event, not a 500
            q.put({"stage": "error", "message": str(exc)})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield _sse({"stage": "open", "id": scenario["id"]})  # which run dir to read from
        while True:
            item = q.get()
            if item is None:
                break
            yield _sse(item)
        yield _sse({"stage": "end"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/agent-run")
def agent_run(req: RunRequest):
    """Like /api/run, but an LLM tool-use agent DECIDES each step — its reasoning and tool
    calls stream into the beats. Falls back to the deterministic pipeline if the agentic
    path is unavailable (offline, no key, or rate-limited), so it always completes."""
    scenario = _scenario(req)
    scenario = {**scenario, "name": scenario.get("name", scenario.get("title", scenario["id"]))}
    q: "queue.Queue" = queue.Queue()
    emit = q.put

    def _region_payload(r):
        return {"region": {"id": r.id, "pixel_bbox": list(r.pixel_bbox), "area_ha": r.area_ha,
                           "ndvi_drop": r.ndvi_drop, "bsi_rise": r.bsi_rise},
                "centroid": [round(v, 6) for v in r.centroid]}

    def worker():
        run_dir = RUNS / scenario["id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        emit({"stage": "open", "id": scenario["id"]})
        emit({"stage": "start", "title": scenario.get("title"), "mode": scenario.get("mode", "quarry"),
              "windows": {"before": scenario["before_window"], "after": scenario["after_window"]}})
        try:
            if config.OFFLINE or config.LLM_PROVIDER not in ("gemini", "claude"):
                raise RuntimeError("agentic loop needs a live LLM (Claude or Gemini)")
            state: dict = {}

            def on_event(ev):
                k = ev.get("kind")
                if k == "text":
                    emit({"stage": "agent", "line": ev["text"]})
                elif k == "tool":
                    emit({"stage": "tool", "name": ev["name"]})
                elif k == "result":
                    _stage_from_tool(ev["name"], scenario, state, run_dir, emit, _region_payload)

            agent.run_agent_stream(scenario, run_dir, on_event, state=state)
            if state.get("region"):
                cls = state.get("classification") or classify.classify_heuristic(
                    state["region"], state.get("dist_coast", 9999), scenario.get("mode"))
                run = democache.assemble_from_state(
                    scenario, state["before"], state["after"], state["region"], cls,
                    state.get("flags", []), state.get("dist_coast", 0.0),
                    state.get("layers") or legality.load_layers(), out_root=RUNS)
                emit({"stage": "done", "run": run})
            else:
                # Valid negative: the before/after composites are already shown (the agent's
                # fetch_imagery emitted them). Signal "no change" without an error overlay so
                # the map stays visible.
                if state.get("before") is not None:
                    democache._save_png(state["before"], run_dir / "before.png")
                    democache._save_png(state["after"], run_dir / "after.png")
                    emit({"stage": "imagery", "before": "before.png", "after": "after.png",
                          "grid": int(scenario["grid"]), "provider": "Sentinel-2 (GEE)"})
                emit({"stage": "nochange", "message": "No significant change detected in this zone/window.",
                      "windows": {"before": scenario["before_window"], "after": scenario["after_window"]}})
        except Exception as exc:  # graceful fallback — deterministic pipeline, still streamed
            emit({"stage": "agent", "line": f"(agentic path unavailable — {exc}; completing the run deterministically.)"})
            try:
                democache.build_run(scenario, out_root=RUNS, use_llm=(not config.OFFLINE),
                                    on_step=lambda stage, payload: emit({"stage": stage, **payload}))
            except democache.NoChangeDetected:
                pass  # build_run already emitted "nochange" + imagery; not an error
            except Exception as exc2:
                emit({"stage": "error", "message": str(exc2)})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            item = q.get()
            if item is None:
                break
            yield _sse(item)
        yield _sse({"stage": "end"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _stage_from_tool(name, scenario, state, run_dir, emit, region_payload):
    """Translate a finished agent tool call into a player beat-stage event."""
    if name == "fetch_imagery" and state.get("before") is not None:
        democache._save_png(state["before"], run_dir / "before.png")
        democache._save_png(state["after"], run_dir / "after.png")
        emit({"stage": "imagery", "before": "before.png", "after": "after.png",
              "grid": int(scenario["grid"]), "provider": "Sentinel-2 (GEE)"})
    elif name == "detect_change" and state.get("region"):
        emit({"stage": "detect", **region_payload(state["region"])})
    elif name == "classify_change" and state.get("classification"):
        c = state["classification"]
        emit({"stage": "classify", "classification": {"label": c.label, "confidence": c.confidence,
              "source": c.source, "reasoning": c.reasoning}})
    elif name == "check_legality" and state.get("region"):
        r, c = state["region"], state.get("classification")
        if c is None:
            c = classify.classify_heuristic(r, state.get("dist_coast", 9999), scenario.get("mode"))
        fnd = Finding(region=r, classification=c, flags=state.get("flags", []),
                      nearest_place=scenario.get("nearest_place", ""),
                      mode=scenario.get("mode", "quarry"), detected_window="")
        grid = int(scenario["grid"])
        overlays = (democache._coastal_overlays(state["before"], grid)
                    if scenario.get("mode") == "coastal"
                    else democache._overlays(scenario, state.get("layers") or legality.load_layers()))
        emit({"stage": "legality", "flags": state.get("flags", []), "severity": severity.score(fnd),
              "overlays": overlays, "distance_to_coast_m": round(state.get("dist_coast", 0.0), 1)})
    elif name == "compile_dossier" and state.get("finding"):
        emit({"stage": "dossier", "dossier": Path(state["finding"].dossier_path).name})


class AlertRequest(BaseModel):
    id: str
    reviewed: bool = False


def _finding_from_dict(d: dict) -> Finding:
    """Rebuild a Finding from a persisted finding.json (enough for the reviewer handoff)."""
    r, c = d["region"], d["classification"]
    region = ChangeRegion(
        id=r["id"], area_ha=r["area_ha"], centroid=tuple(r["centroid"]),
        geo_bbox=tuple(r["geo_bbox"]), pixel_bbox=tuple(r["pixel_bbox"]),
        ndvi_drop=r["ndvi_drop"], bsi_rise=r["bsi_rise"])
    cls = Classification(label=c["label"], confidence=c["confidence"],
                         reasoning=c.get("reasoning", ""), source=c.get("source", "heuristic"))
    return Finding(region=region, classification=cls, flags=d.get("flags", []),
                   nearest_place=d.get("nearest_place", ""), mode=d.get("mode", "quarry"),
                   detected_window=d.get("detected_window", ""),
                   dossier_path=d.get("dossier_path"))


@app.post("/api/alert")
def prepare_alert(req: AlertRequest):
    """Human-in-the-loop gate: prepare (never auto-send) a reviewer alert for a case.

    Refuses unless reviewed=True — mirrors alert.send_to_reviewer's approval gate, which
    is only ever satisfied by an explicit human action (the UI checkbox + button)."""
    fpath = RUNS / req.id / "finding.json"
    if not fpath.exists():
        raise HTTPException(404, f"no finding for case '{req.id}' — run it first")
    finding = _finding_from_dict(json.loads(fpath.read_text()))
    draft = alert.draft_alert(finding)
    try:
        msg = alert.send_to_reviewer(finding, reviewed=req.reviewed, transport="outbox",
                                     draft=draft, out_root=config.OUTPUT_DIR / "outbox")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"ok": True, "message": msg, "draft": draft}


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []   # prior [{role, text}] turns, for follow-up context


_CHAT_SYS = (
    "You are **Raqeeb**, an environmental-intelligence analyst helping an oversight executive in "
    "Lebanon understand and triage satellite-detected candidate violations (illegal quarrying, "
    "coastal encroachment).\n\n"
    "Voice: warm, sharp, decision-oriented — like a trusted analyst, not a form. Hold a real "
    "conversation: use the CONVERSATION SO FAR for follow-ups and pronouns. Reply in concise "
    "markdown — **bold** site names, short '- ' bullet lists, no walls of text. Reply with the "
    "answer text only (no JSON, no preamble like 'Sure').\n\n"
    "Grounding: base every claim on the FINDINGS data below. Never invent sites, numbers, "
    "coordinates, or legal facts. If asked about something not in the data, say what you do and "
    "don't have, and offer a next step (e.g. drawing a box on the map or scanning a named area). "
    "You may explain the method at a high level: 10 m Sentinel-2, same-season cloud-masked "
    "composites, severity scoring, an adversarial second opinion, and a human-review gate.\n\n"
    "Hard rules: every site is a CANDIDATE for human verification, NEVER an accusation; never name "
    "or speculate about individuals; boundaries (coastline, permit zones) are proxies; alerts are "
    "drafted for a person to send, never automatically."
)


def _findings_context() -> list[dict]:
    """Compact, grounded view of every cached case for the chat to reason over."""
    cases = []
    for d in sorted(p for p in RUNS.iterdir() if p.is_dir() and (p / "run.json").exists()):
        r = json.loads((d / "run.json").read_text())
        sev, cls, reg = r.get("severity") or {}, r.get("classification") or {}, r.get("region") or {}
        c = r.get("centroid") or [None, None]
        cases.append({
            "id": r["id"], "title": r["title"], "mode": r["mode"],
            "tier": sev.get("tier"), "score": sev.get("score"), "flags": r.get("flags", []),
            "area_ha": reg.get("area_ha"), "lat": c[1], "lon": c[0],
            "nearest_place": r.get("nearest_place"), "windows": r.get("windows"),
            "classification": cls.get("label"), "confidence": cls.get("confidence"),
            "reasoning": cls.get("reasoning"), "source": cls.get("source"),
            "synthetic": "(synthetic)" in r.get("title", ""),
        })
    return cases


def _brief(question: str, cases: list[dict]) -> tuple[str, list[str]]:
    """Deterministic grounded answer — the offline path AND the fallback if Gemini fails."""
    q = question.lower()
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}
    flagged = sorted((c for c in cases if c["flags"]), key=lambda c: order.get(c["tier"], 4))
    label = lambda c: f"{c['title']} ({c['tier']} {c['score']})"
    if any(w in q for w in ("how many", "count", "number")):
        by: dict = {}
        for c in cases:
            by[c["tier"]] = by.get(c["tier"], 0) + 1
        parts = ", ".join(f"{v} {k}" for k, v in by.items() if k)
        return (f"{len(cases)} candidate sites under watch — {parts}. {len(flagged)} have a rule "
                f"flagged; all are pending human review.", [c["id"] for c in flagged])
    if any(w in q for w in ("coast", "sea", "beirut", "setback", "shore", "landfill")):
        coastal = [c for c in flagged if c["mode"] == "coastal"]
        if coastal:
            return ("Coastal candidates flagged for the public-domain setback: "
                    + "; ".join(label(c) for c in coastal)
                    + ". Candidates for human verification, not accusations.",
                    [c["id"] for c in coastal])
    if flagged:
        top = flagged[0]
        return (f"{len(flagged)} candidate(s) need review — highest is {top['title']} "
                f"({top['tier']} {top['score']}: {', '.join(top['flags'])}). All: "
                + "; ".join(label(c) for c in flagged)
                + ". Each is a candidate for human verification; alerts are drafted, never auto-sent.",
                [c["id"] for c in flagged])
    return (f"{len(cases)} sites under watch; none currently flagged.", [])


def _infer_refs(answer: str, cases: list[dict]) -> list[str]:
    """Which cases did the answer actually mention? (for clickable chips, no JSON needed)"""
    a = answer.lower()
    refs = []
    for c in cases:
        name = c["title"].split("·")[0].strip().lower()
        if (name and name in a) or c["id"].lower() in a:
            refs.append(c["id"])
    return refs


def _chat_answer(question: str, cases: list[dict], history: list[dict] | None = None) -> tuple[str, list[str]]:
    if config.OFFLINE or config.LLM_PROVIDER not in ("gemini", "claude"):
        return _brief(question, cases)
    try:
        from raqeeb import llm
        convo = "".join(f"{t.get('role', 'user')}: {t.get('text', '')}\n" for t in (history or [])[-6:])
        prompt = (f"{_CHAT_SYS}\n\nFINDINGS (JSON):\n{json.dumps(cases)}\n\n"
                  + (f"CONVERSATION SO FAR:\n{convo}\n" if convo else "")
                  + f"USER: {question}\nRAQEEB:")
        gen = llm.claude_generate if config.LLM_PROVIDER == "claude" else llm.gemini_generate
        answer = (gen(contents=prompt).text or "").strip()
        if answer:
            return answer, _infer_refs(answer, cases)
    except Exception:  # LLM unavailable/rate-limited → deterministic grounded brief
        pass
    return _brief(question, cases)


# --- natural-language scan: "scan the coast north of Tripoli" -> a runnable AOI ---
_GAZETTEER = {  # approximate lat/lon for common Lebanese places (gazetteer fallback)
    "beirut": (33.89, 35.50), "tripoli": (34.44, 35.83), "sidon": (33.56, 35.37),
    "saida": (33.56, 35.37), "tyre": (33.27, 35.20), "sour": (33.27, 35.20),
    "jounieh": (33.98, 35.62), "byblos": (34.12, 35.65), "jbeil": (34.12, 35.65),
    "batroun": (34.25, 35.66), "chekka": (34.30, 35.73), "naqoura": (33.11, 35.14),
    "damour": (33.73, 35.45), "chouf": (33.70, 35.60), "zahle": (33.85, 35.90),
    "bekaa": (33.85, 35.90), "akkar": (34.54, 36.10), "bourj hammoud": (33.90, 35.55),
}
_SCAN_SYS = (
    "Extract a satellite scan request for LEBANON. Use your knowledge of Lebanese geography. "
    "Return ONLY JSON: {{\"lat\": <deg>, \"lon\": <deg>, \"span_km\": 3, \"mode\": "
    "\"quarry\"|\"coastal\", \"before\": \"2020-05-01..2020-09-30\", \"after\": "
    "\"2025-05-01..2025-09-30\", \"place\": \"<short name>\"}}. mode=coastal if on/near the "
    "sea, else quarry. Default span_km 3."
)


def _is_scan(q: str) -> bool:
    ql = q.lower()
    return "scan" in ql or ql.startswith(("analyze", "analyse", "check the", "look at", "monitor "))


def _bbox(lat: float, lon: float, span_km: float) -> list[float]:
    dlat = span_km / 111.0
    dlon = span_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return [round(lon - dlon / 2, 4), round(lat - dlat / 2, 4),
            round(lon + dlon / 2, 4), round(lat + dlat / 2, 4)]


def _scan_scenario(question: str) -> dict | None:
    """Parse an NL scan request into a runnable AOI (Gemini, with a gazetteer fallback)."""
    lat = lon = None
    mode, place, span = "quarry", None, 3.0
    before, after = "2020-05-01..2020-09-30", "2025-05-01..2025-09-30"
    if not config.OFFLINE and config.LLM_PROVIDER in ("gemini", "claude"):
        try:
            from raqeeb import llm
            gen = llm.claude_generate if config.LLM_PROVIDER == "claude" else llm.gemini_generate
            raw = gen(contents=f"{_SCAN_SYS}\n\nREQUEST: {question}").text
            s, e = raw.find("{"), raw.rfind("}")
            d = json.loads(raw[s:e + 1])
            lat, lon = float(d["lat"]), float(d["lon"])
            mode = d.get("mode", "quarry"); place = d.get("place")
            before, after = d.get("before", before), d.get("after", after)
            span = float(d.get("span_km", 3) or 3)
        except Exception:
            lat = lon = None
    if lat is None:  # gazetteer fallback (works offline / if the LLM call fails)
        ql = question.lower()
        for name, (la, lo) in _GAZETTEER.items():
            if name in ql:
                lat, lon, place = la, lo, name.title()
                break
        if any(w in ql for w in ("coast", "sea", "shore", "landfill", "beach", "waterfront")):
            mode = "coastal"
    if lat is None:
        return None
    return {"bbox": _bbox(lat, lon, max(2.0, min(config.SCAN_MAX_KM, span))), "mode": mode,
            "before_window": before, "after_window": after,
            "title": f"{place or 'Scan'} (scan)"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Executive Q&A grounded in the findings; an NL 'scan …' request returns a runnable AOI."""
    q = req.question.strip()
    if _is_scan(q):
        sc = _scan_scenario(q)
        if sc:
            place = sc["title"].replace(" (scan)", "")
            return {"answer": f"Scanning {place} on live Sentinel-2 — running the agent now.",
                    "cases": [], "action": {"type": "scan", "scenario": sc}}
        return {"answer": "I couldn't pin that to a location in Lebanon — try naming a town or "
                          "a stretch of coast (e.g. 'scan the coast at Chekka').", "cases": []}
    answer, refs = _chat_answer(q, _findings_context(), req.history)
    return {"answer": answer, "cases": refs}


# static player — mounted LAST so /api/* routes win; html=True serves index.html at "/".
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
