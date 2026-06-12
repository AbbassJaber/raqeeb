"""The agent.

`run_agent` is the autonomous perceive -> reason -> act loop. It returns a
narration trace (the agent's reasoning, step by step) and a Finding.

Offline it runs a deterministic orchestration over the tools. Online,
`run_agent_with_claude` lets Claude select and sequence the same tools via
tool use; both share one `dispatch` so behaviour stays identical.
"""
from __future__ import annotations
import json
from pathlib import Path
from shapely.geometry import Point, box

from . import config, imagery, detect, classify, legality, dossier, alert
from .models import Finding


def run_agent(scenario: dict | None = None, out_dir: Path | None = None, on_step=None):
    """Deterministic orchestration. Returns (narration: list[str], finding | None).

    If ``on_step`` is given it's called as ``on_step(stage, line, data)`` after each
    stage (stages: start, imagery, detect, classify, legality, dossier, alert) so a UI
    can show progress live during a slow (online) run. ``data`` carries the relevant
    objects: before/after arrays, the region, the classification, flags, the dossier
    path, and the drafted alert text.
    """
    scenario = scenario or config.DEMO_SCENARIO
    out_dir = Path(out_dir or config.OUTPUT_DIR)
    narration: list[str] = []

    def emit(stage, line, **data):
        narration.append(line)
        if on_step:
            on_step(stage, line, data)

    emit("start", f"Monitoring {scenario['name']} — "
                  f"{scenario['before_window']} vs {scenario['after_window']}.")

    before, after = imagery.get_composites(scenario)
    emit("imagery", "Pulled before/after composites and aligned them.",
         before=before, after=after)

    regions = detect.detect(before, after, scenario)
    if not regions:
        emit("detect", "No significant change detected.", region=None)
        return narration, None
    region = regions[0]
    emit("detect", f"Detected {region.area_ha} ha of change at "
                   f"{region.centroid[1]:.4f} N, {region.centroid[0]:.4f} E "
                   f"(NDVI drop {region.ndvi_drop}, BSI rise {region.bsi_rise}).",
         region=region)

    layers = legality.load_layers()
    dist_coast = legality.distance_to_coast_m(Point(region.centroid), layers)

    cls = classify.classify(region, before, after, dist_coast)
    emit("classify", f"Classified as {cls.label} (confidence {cls.confidence}; {cls.source}).",
         classification=cls)

    looks_quarry = cls.label == "quarry_expansion"
    flags = legality.assess_flags(region, after, scenario, looks_quarry, layers)
    emit("legality", "Legality check: " + ("; ".join(flags) if flags else "no rule triggered") + ".",
         flags=flags)

    finding = Finding(region=region, classification=cls, flags=flags,
                      nearest_place=scenario.get("nearest_place", ""),
                      mode=scenario.get("mode", "quarry"),
                      detected_window=f"{scenario['before_window']} -> {scenario['after_window']}")

    viz = dossier.render_before_after(before, after, finding, out_dir)
    finding.dossier_path = str(dossier.build_dossier(finding, viz, out_dir))
    emit("dossier", f"Compiled evidence dossier -> {finding.dossier_path}",
         path=finding.dossier_path)

    draft = alert.draft_alert(finding)
    emit("alert", "Drafted an alert for human review (not sent):\n" + draft, draft=draft)

    return narration, finding


# --- online: Claude chooses and sequences the same tools --------------------
#
# Claude drives the SAME pipeline functions used by run_agent, via tool use. The
# tools operate on shared state (numpy arrays can't pass through the model), and
# every result stays framed as a candidate for human review.

_SYSTEM = (
    "You are Raqeeb, an AI agent that helps Lebanese authorities and NGOs find "
    "likely environmental violations from satellite imagery. Use the tools to: fetch "
    "same-season before/after imagery, detect land-cover change, classify the largest "
    "change, check it against legal reference layers, then compile an evidence dossier "
    "and draft an alert.\n\n"
    "HARD RULES:\n"
    "- Every output is a CANDIDATE for human verification, never an accusation or a "
    "legal verdict. Never state that a violation is confirmed.\n"
    "- Never send an alert or contact anyone — you only DRAFT for a human to review.\n"
    "- Do not name or speculate about individuals.\n"
    "When finished, give a short plain-language summary of the candidate finding and "
    "what a human reviewer should verify (the legal layers are proxies)."
)

_TOOLS = [
    {"name": "fetch_imagery",
     "description": "Fetch same-season before/after Sentinel-2 composites for the monitored area.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "detect_change",
     "description": "Detect and measure land-cover change; returns candidate change regions, largest first.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "classify_change",
     "description": "Classify the largest change region from the before/after imagery (vision).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "check_legality",
     "description": "Check the largest change region against protected-area, coastal-setback and permitted-quarry layers.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "compile_dossier",
     "description": "Compile the one-page evidence dossier (PDF + before/after image) for the finding.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "draft_alert",
     "description": "Draft (do NOT send) an alert for a human reviewer.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _dispatch(name, args, state):  # pragma: no cover - requires ANTHROPIC_API_KEY
    scenario = state["scenario"]
    if name == "fetch_imagery":
        state["before"], state["after"] = imagery.get_composites(scenario)
        return {"status": "fetched", "grid": scenario["grid"], "bbox": scenario["bbox"]}

    if name == "detect_change":
        regions = detect.detect(state["before"], state["after"], scenario)
        state["regions"] = regions
        if not regions:
            return {"regions": [], "note": "no change above thresholds"}
        state["region"] = regions[0]
        state["layers"] = legality.load_layers()
        state["dist_coast"] = legality.distance_to_coast_m(Point(regions[0].centroid), state["layers"])
        return {"regions": [{"id": r.id, "area_ha": r.area_ha, "centroid": r.centroid,
                             "ndvi_drop": r.ndvi_drop, "bsi_rise": r.bsi_rise} for r in regions[:5]],
                "distance_to_coast_m": round(state["dist_coast"], 1)}

    if name == "classify_change":
        r = state.get("region")
        if r is None:
            return {"error": "run detect_change first"}
        cls = classify.classify(r, state["before"], state["after"], state["dist_coast"])
        state["classification"] = cls
        return {"label": cls.label, "confidence": cls.confidence,
                "reasoning": cls.reasoning, "source": cls.source}

    if name == "check_legality":
        r = state.get("region")
        if r is None:
            return {"error": "run detect_change first"}
        cls = state.get("classification")
        looks_quarry = bool(cls and cls.label == "quarry_expansion")
        flags = legality.assess_flags(r, state["after"], scenario, looks_quarry, state["layers"])
        state["flags"] = flags
        return {"flags": flags, "is_candidate_violation": bool(flags),
                "note": "legal layers are proxies; confirm against official records"}

    if name == "compile_dossier":
        r = state.get("region")
        if r is None:
            return {"error": "run detect_change first"}
        cls = state.get("classification") or classify.classify_heuristic(r, state["dist_coast"])
        finding = Finding(region=r, classification=cls, flags=state.get("flags", []),
                          nearest_place=scenario.get("nearest_place", ""),
                          mode=scenario.get("mode", "quarry"),
                          detected_window=f"{scenario['before_window']} -> {scenario['after_window']}")
        viz = dossier.render_before_after(state["before"], state["after"], finding, state["out_dir"])
        finding.dossier_path = str(dossier.build_dossier(finding, viz, state["out_dir"]))
        state["finding"] = finding
        return {"dossier_path": finding.dossier_path, "is_candidate_violation": finding.is_violation}

    if name == "draft_alert":
        finding = state.get("finding")
        if finding is None:
            return {"error": "compile the dossier first"}
        state["alert"] = alert.draft_alert(finding)
        return {"draft": state["alert"], "sent": False}

    return {"error": f"unknown tool {name}"}


def run_agent_with_claude(scenario: dict | None = None,
                          out_dir: Path | None = None):  # pragma: no cover - needs ANTHROPIC_API_KEY
    """Claude autonomously sequences the same pipeline tools via tool use.

    Returns (narration: list[str], finding | None) — the same shape as run_agent,
    so callers/UI can use either path. Requires ANTHROPIC_API_KEY.
    """
    import anthropic
    client = anthropic.Anthropic()
    scenario = scenario or config.DEMO_SCENARIO
    state = {"scenario": scenario, "out_dir": Path(out_dir or config.OUTPUT_DIR)}
    narration: list[str] = []
    messages = [{"role": "user", "content":
        f"Monitor {scenario['name']} ({scenario['before_window']} vs "
        f"{scenario['after_window']}) and report any candidate violation, explaining each step."}]

    for _ in range(16):  # guard against runaway tool loops
        resp = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=1500,
                                      system=_SYSTEM, tools=_TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        for b in resp.content:
            if getattr(b, "type", "") == "text" and b.text.strip():
                narration.append(b.text.strip())
        if resp.stop_reason != "tool_use":
            break
        results = [{"type": "tool_result", "tool_use_id": b.id,
                    "content": json.dumps(_dispatch(b.name, b.input, state), default=str)}
                   for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "user", "content": results})

    return narration, state.get("finding")


def run_agent_with_gemini(scenario: dict | None = None,
                          out_dir: Path | None = None):  # pragma: no cover - needs GEMINI_API_KEY
    """Same orchestration as run_agent_with_claude, driven by Google Gemini function
    calling. Reuses the identical _dispatch + _TOOLS + system prompt. Requires
    GEMINI_API_KEY (Google AI Studio, free tier). Returns (narration, finding | None).
    """
    from google.genai import types
    from . import llm

    scenario = scenario or config.DEMO_SCENARIO
    state = {"scenario": scenario, "out_dir": Path(out_dir or config.OUTPUT_DIR)}
    narration: list[str] = []

    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t["description"],
                                  parameters_json_schema=t["input_schema"]) for t in _TOOLS])
    cfg = types.GenerateContentConfig(
        system_instruction=_SYSTEM, tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=(
        f"Monitor {scenario['name']} ({scenario['before_window']} vs "
        f"{scenario['after_window']}) and report any candidate violation, explaining each step."))])]

    for _ in range(16):  # guard against runaway tool loops
        resp = llm.gemini_generate(contents=contents, gen_config=cfg)
        cand = resp.candidates[0]
        contents.append(cand.content)
        for part in (cand.content.parts or []):
            if getattr(part, "text", None) and part.text.strip():
                narration.append(part.text.strip())
        calls = resp.function_calls or []
        if not calls:
            break
        replies = []
        for fc in calls:
            out = _dispatch(fc.name, dict(fc.args or {}), state)
            out = json.loads(json.dumps(out, default=str))  # ensure JSON-clean types
            replies.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
        contents.append(types.Content(role="user", parts=replies))

    return narration, state.get("finding")


def run_agent_with_llm(scenario: dict | None = None, out_dir: Path | None = None):  # pragma: no cover
    """Route to the configured LLM orchestrator (config.LLM_PROVIDER)."""
    if config.LLM_PROVIDER == "gemini":
        return run_agent_with_gemini(scenario, out_dir)
    return run_agent_with_claude(scenario, out_dir)


def run_agent_claude_stream(scenario: dict, out_dir, on_event, state=None):  # pragma: no cover - needs key
    """Streaming Claude tool-use loop for the live 'agentic run' (Claude analog of
    ``run_agent_gemini_stream``). Calls ``on_event({"kind": "text"|"tool"|"result", ...})``
    as Claude reasons and calls each tool, and populates the shared ``state`` dict
    (before/after/region/classification/flags/dist_coast/finding) — pass one in to read
    tool results mid-stream. Requires ANTHROPIC_API_KEY."""
    import anthropic
    client = anthropic.Anthropic()

    state = {} if state is None else state
    state.setdefault("scenario", scenario)
    state.setdefault("out_dir", Path(out_dir or config.OUTPUT_DIR))
    messages = [{"role": "user", "content": (
        f"Monitor {scenario['name']} ({scenario['before_window']} vs "
        f"{scenario['after_window']}). Briefly explain your reasoning before each tool call, "
        "then report the candidate finding.")}]

    for _ in range(16):  # guard against runaway tool loops
        # Stream so the browser sees the agent's reasoning token-by-token; get_final_message()
        # then gives us the complete turn (incl. tool_use blocks) to act on.
        with client.messages.stream(model=config.CLAUDE_MODEL, max_tokens=1500,
                                    system=_SYSTEM, tools=_TOOLS, messages=messages) as stream:
            for ev in stream:
                if ev.type == "content_block_stop" and getattr(ev.content_block, "type", "") == "text":
                    text = ev.content_block.text.strip()
                    if text:
                        on_event({"kind": "text", "text": text})
            resp = stream.get_final_message()

        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        replies = []
        for b in resp.content:
            if getattr(b, "type", "") != "tool_use":
                continue
            on_event({"kind": "tool", "name": b.name})
            out = _dispatch(b.name, b.input, state)
            out = json.loads(json.dumps(out, default=str))  # JSON-clean types
            on_event({"kind": "result", "name": b.name, "result": out})
            replies.append({"type": "tool_result", "tool_use_id": b.id,
                            "content": json.dumps(out, default=str)})
        messages.append({"role": "user", "content": replies})
    return state


def run_agent_stream(scenario: dict, out_dir, on_event, state=None):  # pragma: no cover - needs key
    """Route the streaming agentic run to the configured provider (config.LLM_PROVIDER)."""
    if config.LLM_PROVIDER == "gemini":
        return run_agent_gemini_stream(scenario, out_dir, on_event, state=state)
    return run_agent_claude_stream(scenario, out_dir, on_event, state=state)


def run_agent_gemini_stream(scenario: dict, out_dir, on_event, state=None):  # pragma: no cover - needs key
    """Streaming Gemini tool-use loop for the live 'agentic run'. Calls
    ``on_event({"kind": "text"|"tool"|"result", ...})`` as the agent reasons and calls
    each tool, and populates the shared ``state`` dict (before/after/region/classification/
    flags/dist_coast/finding) — pass one in to read tool results mid-stream. Requires GEMINI_API_KEY."""
    from google.genai import types
    from . import llm

    state = {} if state is None else state
    state.setdefault("scenario", scenario)
    state.setdefault("out_dir", Path(out_dir or config.OUTPUT_DIR))
    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t["description"],
                                  parameters_json_schema=t["input_schema"]) for t in _TOOLS])
    cfg = types.GenerateContentConfig(
        system_instruction=_SYSTEM, tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=(
        f"Monitor {scenario['name']} ({scenario['before_window']} vs "
        f"{scenario['after_window']}). Briefly explain your reasoning before each tool call, "
        "then report the candidate finding."))])]

    for _ in range(16):
        resp = llm.gemini_generate(contents=contents, gen_config=cfg)
        cand = resp.candidates[0]
        contents.append(cand.content)
        for part in (cand.content.parts or []):
            if getattr(part, "text", None) and part.text.strip():
                on_event({"kind": "text", "text": part.text.strip()})
        calls = resp.function_calls or []
        if not calls:
            break
        replies = []
        for fc in calls:
            on_event({"kind": "tool", "name": fc.name})
            out = _dispatch(fc.name, dict(fc.args or {}), state)
            out = json.loads(json.dumps(out, default=str))
            on_event({"kind": "result", "name": fc.name, "result": out})
            replies.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
        contents.append(types.Content(role="user", parts=replies))
    return state
