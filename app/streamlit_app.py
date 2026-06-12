"""Streamlit UI for the Raqeeb agent — Orbital Command styling.

    ./.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py

Draw a zone on the map, pick before/after windows, and watch the agent fetch imagery,
detect change, classify it, check legality, and compile a dossier — then hand a drafted
alert to a human reviewer. Offline (synthetic imagery) by default; set RAQEEB_OFFLINE=0 +
Earth Engine auth to monitor the drawn zone with real Sentinel-2.
"""
import math
import sys
from pathlib import Path

import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raqeeb import config, imagery, alert, severity       # noqa: E402
from raqeeb.agent import run_agent                        # noqa: E402

st.set_page_config(page_title="Raqeeb", page_icon="🛰️", layout="wide")

# --- Orbital Command styling ------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Spline+Sans+Mono:wght@400;500&display=swap');
.stApp { background: radial-gradient(1200px 520px at 72% -12%, #0d1f3a, #070b14 60%), #0b1220;
         font-family: 'Manrope', system-ui, sans-serif; }
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, h4 { color: #f1f5fb; font-weight: 700; letter-spacing: .01em; }
code, pre, [data-testid="stCode"], [data-testid="stCode"] code,
[data-testid="stMetricValue"] { font-family: 'Spline Sans Mono', ui-monospace, monospace; }

/* brand header */
.rq-head { display:flex; align-items:flex-end; justify-content:space-between;
    border-bottom:1px solid #1b2942; padding-bottom:12px; }
.rq-brand { font-size:22px; font-weight:700; color:#f1f5fb; }
.rq-brand b { color:#6ea8fe; }
.rq-kicker { font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:#6b7f9e; margin-top:4px; }
.rq-pill { font-size:12px; font-weight:600; padding:4px 12px; border-radius:20px;
    background:#13294a; color:#6ea8fe; border:1px solid #24406a; white-space:nowrap; }
.rq-pill.live { background:#163a2a; color:#5fd0a8; border-color:#1f5a40; }

/* panels (st.container(border=True)) — depth + atmosphere */
[data-testid="stVerticalBlockBorderWrapper"] { background:linear-gradient(180deg,#0e1a33cc,#0b1322cc);
    border:1px solid #1b2942; border-radius:12px;
    box-shadow:0 10px 34px #00071a66, inset 0 1px 0 #ffffff08; }

/* metrics as cards */
[data-testid="stMetric"] { background:#0c1526; border:1px solid #1b2942; border-radius:10px;
    padding:12px 14px; }
[data-testid="stMetricLabel"] p { color:#8aa0c0; text-transform:uppercase; letter-spacing:.1em;
    font-size:11px; }
[data-testid="stMetricValue"] { color:#6ea8fe; }

.stButton > button, .stDownloadButton > button { border-radius:8px; font-weight:600; }
[data-testid="stCode"] { background:#0c1526; border:1px solid #1b2942; border-radius:8px; }

/* step rail + telemetry */
.rq-rail { font-family:'Spline Sans Mono', monospace; font-size:13px; line-height:1.85; }
.rq-rail .ph { color:#6ea8fe; text-transform:uppercase; letter-spacing:.14em; font-size:11px; margin-top:8px; }
.rq-rail .done { color:#dbe4f0; } .rq-rail .pending { color:#46587a; }
.rq-tel { font-family:'Spline Sans Mono', monospace; color:#8aa0c0; font-size:13px; margin-top:8px; }
.rq-tel b { color:#dbe4f0; }

/* refined controls + containers */
.stButton > button[kind="primary"], .stDownloadButton > button{
  background:linear-gradient(180deg,#6ea8fe,#4f86e0);border:0;color:#06101f;
  box-shadow:0 4px 16px #6ea8fe40;transition:box-shadow .2s,transform .05s;}
.stButton > button[kind="primary"]:hover{box-shadow:0 6px 24px #6ea8fe70;}
.stButton > button[kind="primary"]:active{transform:translateY(1px);}
[data-testid="stExpander"] details, [data-testid="stStatusWidget"]{
  background:#0c1526;border:1px solid #1b2942;border-radius:10px;}
.rq-head{position:relative;}
.rq-head:after{content:"";position:absolute;left:0;bottom:-1px;width:140px;height:2px;
  background:linear-gradient(90deg,#6ea8fe,transparent);}
</style>
""", unsafe_allow_html=True)

_LIVE = not config.OFFLINE
st.markdown(f"""
<div class="rq-head">
  <div>
    <div class="rq-brand"><b>RAQEEB</b></div>
    <div class="rq-kicker">Environmental monitoring · Lebanon · metric CRS {config.METRIC_CRS}</div>
  </div>
  <div class="rq-pill {'live' if _LIVE else ''}">{'● LIVE · Sentinel-2' if _LIVE else '○ OFFLINE · synthetic'}</div>
</div>
<div class="rq-kicker" style="margin:8px 0 14px;">Every output is a candidate for human
verification, never an accusation — alerts are drafted for a person to send.</div>
""", unsafe_allow_html=True)


def _drawn_bbox(map_data) -> tuple[float, float, float, float] | None:
    """Extract (min_lon, min_lat, max_lon, max_lat) from the last drawn rectangle."""
    if not map_data:
        return None
    feat = map_data.get("last_active_drawing")
    if not feat:
        draws = map_data.get("all_drawings") or []
        feat = draws[-1] if draws else None
    if not feat or feat.get("geometry", {}).get("type") != "Polygon":
        return None
    ring = feat["geometry"]["coordinates"][0]
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    return (min(lons), min(lats), max(lons), max(lats))


def _grid_for(bbox) -> int:
    """Pick a square grid so pixels are ~PIXEL_M metres, bounded for responsiveness."""
    min_lon, min_lat, max_lon, max_lat = bbox
    mid = math.radians((min_lat + max_lat) / 2)
    w_m = (max_lon - min_lon) * math.cos(mid) * 111_320
    h_m = (max_lat - min_lat) * 111_320
    return int(min(512, max(64, round(max(w_m, h_m) / config.PIXEL_M))))


# Perceive -> Reason -> Act, as the cinematic step-rail.
_RAIL = [("Perceive", [("imagery", "Fetch composites")]),
         ("Reason", [("detect", "Detect change"), ("classify", "Classify"),
                     ("legality", "Check legality")]),
         ("Act", [("dossier", "Compile dossier"), ("alert", "Draft alert")])]


def _rail_html(reached) -> str:
    html = '<div class="rq-rail">'
    for phase, steps in _RAIL:
        html += f'<div class="ph">{phase}</div>'
        for key, label in steps:
            done = key in reached
            html += f'<div class="{"done" if done else "pending"}">{"✓" if done else "○"} {label}</div>'
    return html + "</div>"


# --- map + controls ---------------------------------------------------------
left, right = st.columns([3, 2])
with left:
    with st.container(border=True):
        st.subheader("1 · Draw the zone to monitor")
        m = folium.Map(location=[33.85, 35.70], zoom_start=9, tiles="CartoDB dark_matter")
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="Satellite", overlay=False, control=True).add_to(m)
        Draw(draw_options={"rectangle": True, "polyline": False, "polygon": False,
                           "circle": False, "marker": False, "circlemarker": False},
             edit_options={"edit": False}).add_to(m)
        folium.LayerControl().add_to(m)
        # returned_objects → only rerun when a rectangle is drawn, NOT on pan/zoom/scroll
        # (otherwise scrolling the map clears the live run view).
        map_data = st_folium(m, height=460, use_container_width=True,
                             returned_objects=["last_active_drawing", "all_drawings"])
        bbox = _drawn_bbox(map_data)

with right:
    with st.container(border=True):
        st.subheader("2 · Windows & run")
        mode = st.radio("Detection mode", ["quarry", "coastal"], horizontal=True)
        before_window = st.text_input("Before window (start..end)", "2018-05-01..2018-09-30")
        after_window = st.text_input("After window (start..end)", "2024-05-01..2024-09-30")
        place = st.text_input("Place label (for the dossier)", "Drawn zone, Lebanon")
        if bbox:
            grid = _grid_for(bbox)
            st.success(f"Zone: {bbox[0]:.4f}, {bbox[1]:.4f} → {bbox[2]:.4f}, {bbox[3]:.4f}  "
                       f"({grid}×{grid} px @ ~{config.PIXEL_M} m)")
        else:
            st.info("Draw a rectangle on the map. Without one, the synthetic demo AOI is used.")
        run = st.button("▶  Run agent", type="primary", use_container_width=True)


# --- run: a live, animated status so the wait always shows progress ---------
_LABELS = {"start": "Initialising…", "imagery": "Fetching same-season composites…",
           "detect": "Detecting change…", "classify": "Classifying (vision)…",
           "legality": "Checking legality…", "dossier": "Compiling dossier…",
           "alert": "Drafting alert…"}

if run:
    scenario = ({
        "name": place, "mode": mode, "bbox": tuple(bbox),
        "before_window": before_window, "after_window": after_window,
        "grid": _grid_for(bbox), "nearest_place": place,
    } if bbox else config.DEMO_SCENARIO)

    # st.status shows a client-side spinner that keeps animating during the long
    # (blocking) Earth Engine fetch + LLM call — the in-progress indicator.
    with st.status("Monitoring the zone…", expanded=True) as status:
        rail_col, stage_col = st.columns([1, 3])
        rail_box, tel_box = rail_col.empty(), rail_col.empty()
        stage_box = stage_col.empty()
        reached, captured = [], {}
        rail_box.markdown(_rail_html(reached), unsafe_allow_html=True)

        def on_step(stage, line, data):
            status.update(label=_LABELS.get(stage, "Working…"))
            if stage not in reached:
                reached.append(stage)
            rail_box.markdown(_rail_html(reached), unsafe_allow_html=True)
            if stage == "imagery":
                with stage_box.container():
                    c1, c2 = st.columns(2)
                    c1.image(imagery.to_rgb(data["before"]), caption="Before", use_container_width=True)
                    c2.image(imagery.to_rgb(data["after"]), caption="After", use_container_width=True)
            if stage == "detect" and data.get("region") is not None:
                captured["region"] = data["region"]
            if stage == "classify":
                r, c = captured.get("region"), data["classification"]
                tel = (f'NDVI <b>↓{abs(r.ndvi_drop):.2f}</b> · BSI <b>↑{r.bsi_rise:.2f}</b> · '
                       f'<b>{r.area_ha} ha</b><br>{c.label} · <b>{c.confidence}</b> ({c.source})'
                       if r else f'{c.label} · <b>{c.confidence}</b>')
                tel_box.markdown(f'<div class="rq-tel">{tel}</div>', unsafe_allow_html=True)
            if stage == "alert":
                captured["draft"] = data.get("draft", "")

        try:
            narration, finding = run_agent(scenario, on_step=on_step)
        except Exception as exc:  # surface live-fetch / auth problems clearly
            status.update(label="Run failed", state="error")
            st.error(f"Run failed: {exc}")
            st.stop()
        status.update(label="Analysis complete", state="complete", expanded=False)

    st.session_state["result"] = {"narration": narration, "finding": finding,
                                  "draft": captured.get("draft", "")}
    st.session_state.pop("sent", None)


# --- results + human-gated reviewer handoff (persist across reruns) ---------
result = st.session_state.get("result")
if result and result["finding"]:
    finding = result["finding"]

    sev = severity.score(finding)
    with st.container(border=True):
        st.subheader("Finding")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Change area", f"{finding.region.area_ha} ha")
        m2.metric("Class", finding.classification.label)
        m3.metric("Confidence", finding.classification.confidence)
        m4.metric("Severity", f"{sev['tier']} ({sev['score']:.0f})")
        if finding.is_violation:
            st.error("Candidate violation: " + "; ".join(finding.flags))
        else:
            st.info("No rule triggered.")
        with st.expander(f"Why severity {sev['tier']} · {sev['score']:.0f}/100"):
            for fct in sev["factors"]:
                st.markdown(f"- **+{fct['points']}** · {fct['label']}")

        viz = config.OUTPUT_DIR / f"{finding.region.id}_before_after.png"
        if viz.exists():
            st.image(str(viz), caption="Before / After (change boxed)", use_container_width=True)

        with st.expander("Agent reasoning trace"):
            for line in result["narration"]:
                st.markdown(f"- {line}")

        if finding.dossier_path and Path(finding.dossier_path).exists():
            st.download_button("⤓  Download evidence dossier (PDF)",
                               data=Path(finding.dossier_path).read_bytes(),
                               file_name=Path(finding.dossier_path).name,
                               mime="application/pdf")

    with st.container(border=True):
        st.subheader("Send to a human reviewer")
        st.caption(f"Transport: **{config.REVIEW_TRANSPORT}** "
                   "(set RAQEEB_REVIEW_TRANSPORT = outbox | email | webhook). The agent never "
                   "sends — a person reviews this draft and dispatches it.")
        st.code(result["draft"] or "(no draft)", language="text")
        reviewed = st.checkbox("I have reviewed this candidate and confirm it should go to a reviewer.")
        if st.button("✉  Send to reviewer", disabled=not reviewed, type="primary"):
            try:
                st.session_state["sent"] = alert.send_to_reviewer(finding, reviewed=True)
            except Exception as exc:
                st.session_state["sent"] = f"Send failed: {exc}"
        if st.session_state.get("sent"):
            st.success(st.session_state["sent"])

elif result:
    st.info("No significant change detected in this zone/window.")
    with st.expander("Agent reasoning trace"):
        for line in result["narration"]:
            st.markdown(f"- {line}")
else:
    st.caption("Draw a zone, set the windows, and press **Run agent**.")
