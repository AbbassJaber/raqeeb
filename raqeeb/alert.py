"""Draft an alert for a flagged finding.

Draft ONLY — never sent automatically. A human reviews and decides. `send_to_reviewer`
routes a draft + dossier to a person, and only on an explicit human action (it refuses
unless `reviewed=True`). The agent never calls it.
"""
from __future__ import annotations
import json
import shutil
from pathlib import Path

from . import config
from .models import Finding

_RECIPIENTS = "Municipality / Ministry of Environment / environmental NGO"
_RECIPIENTS_AR = "البلدية / وزارة البيئة / منظمة بيئية"


_ALERT_PROMPT = (
    "Write a concise, factual alert (<=120 words) to a Lebanese municipality about a "
    "satellite-flagged candidate violation. Frame it as requiring verification, not an "
    "accusation, and do not name individuals. Details: {details}"
)
# Appended when the operator's UI is in Arabic — keep the alert ready for a local recipient.
_ALERT_AR = ("\n\nWrite the entire alert in Modern Standard Arabic (العربية الفصحى), suitable "
             "for a Lebanese municipality. Keep it a candidate requiring verification, never an "
             "accusation, and do not name individuals.")


def draft_alert(finding: Finding, locale: str = "en") -> str:
    ar = str(locale or "en").lower().startswith("ar")
    if not config.OFFLINE:
        try:
            if config.LLM_PROVIDER == "gemini":
                return _draft_with_gemini(finding, ar)
            return _draft_with_claude(finding, ar)
        except Exception:
            pass  # fall back to the template
    f = finding
    if ar:
        return (
            f"إلى: {_RECIPIENTS_AR}\n"
            f"الموضوع: احتمال {f.classification.label.replace('_', ' ')} — {f.nearest_place}\n\n"
            f"رصد التحليل الفضائي ~{f.region.area_ha} هكتار من التغيّر عند "
            f"{f.region.centroid[1]:.5f} شمالاً، {f.region.centroid[0]:.5f} شرقاً "
            f"({f.detected_window}). {('؛ '.join(f.flags)) or 'يُظهر تغيّراً ملحوظاً في الغطاء الأرضي'}. "
            f"التصنيف: {f.classification.label} ({f.classification.confidence:.2f}).\n\n"
            f"مرفق ملف أدلّة للتحقق. هذا إشعار مرشّح آلي، وليس مخالفة مؤكّدة.\n\n"
            f"[مسودّة — يُراجَع قبل الإرسال]"
        )
    return (
        f"To: {_RECIPIENTS}\n"
        f"Subject: Possible {f.classification.label.replace('_', ' ')} — {f.nearest_place}\n\n"
        f"Satellite analysis flagged ~{f.region.area_ha} ha of change at "
        f"{f.region.centroid[1]:.5f} N, {f.region.centroid[0]:.5f} E "
        f"({f.detected_window}). It {('; '.join(f.flags)) or 'shows notable land-cover change'}. "
        f"Classified as {f.classification.label} ({f.classification.confidence:.2f}).\n\n"
        f"An evidence dossier is attached for verification. This is an automated "
        f"candidate flag, not a confirmed violation.\n\n"
        f"[DRAFT — review before sending]"
    )


def _prompt(finding: Finding, ar: bool) -> str:
    return _ALERT_PROMPT.format(details=finding.to_dict()) + (_ALERT_AR if ar else "")


def _draft_with_claude(finding: Finding, ar: bool = False) -> str:  # pragma: no cover
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=350,
        messages=[{"role": "user", "content": _prompt(finding, ar)}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _draft_with_gemini(finding: Finding, ar: bool = False) -> str:  # pragma: no cover
    from . import llm
    resp = llm.gemini_generate(contents=_prompt(finding, ar))
    return resp.text


# --- reviewer handoff (human-in-the-loop; never auto-sent) ------------------

def send_to_reviewer(finding: Finding, reviewed: bool = False, transport: str | None = None,
                     draft: str | None = None, out_root=None) -> str:
    """Route a drafted candidate to a HUMAN reviewer.

    Human-approval gate: this refuses unless ``reviewed=True`` (set only after a person
    has reviewed the candidate). The agent NEVER calls this — only an explicit human
    action (e.g. a UI button) does. Transport defaults to config.REVIEW_TRANSPORT:
    "outbox" (local, no creds), "email" (SMTP), or "webhook". Returns a confirmation.
    """
    if not reviewed:
        raise PermissionError(
            "Human review required: call send_to_reviewer(..., reviewed=True) only after "
            "a person has reviewed the candidate. Alerts are never sent autonomously.")
    draft = draft if draft is not None else draft_alert(finding)
    transport = (transport or config.REVIEW_TRANSPORT).lower()
    if transport == "email":
        return _send_email(finding, draft)
    if transport == "webhook":
        return _send_webhook(finding, draft)
    return _send_outbox(finding, draft, out_root)


def _send_outbox(finding: Finding, draft: str, out_root=None) -> str:
    base = Path(out_root) if out_root else (config.OUTPUT_DIR / "outbox")
    out = base / finding.region.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "alert.txt").write_text(draft, encoding="utf-8")
    (out / "finding.json").write_text(
        json.dumps(finding.to_dict(), indent=2, default=str), encoding="utf-8")
    if finding.dossier_path and Path(finding.dossier_path).exists():
        shutil.copy(finding.dossier_path, out / Path(finding.dossier_path).name)
    return f"Queued for a human reviewer at {out} (local outbox — nothing sent externally)."


def _send_email(finding: Finding, draft: str) -> str:  # pragma: no cover - needs SMTP creds
    import smtplib
    from email.message import EmailMessage

    if not (config.SMTP_HOST and config.REVIEWER_EMAIL):
        raise RuntimeError("Email transport needs RAQEEB_SMTP_HOST and RAQEEB_REVIEWER_EMAIL.")
    msg = EmailMessage()
    msg["Subject"] = f"[Raqeeb] Candidate for review — {finding.nearest_place}"
    msg["From"] = config.SMTP_USER or config.REVIEWER_EMAIL
    msg["To"] = config.REVIEWER_EMAIL
    msg.set_content(draft)
    if finding.dossier_path and Path(finding.dossier_path).exists():
        msg.add_attachment(Path(finding.dossier_path).read_bytes(), maintype="application",
                           subtype="pdf", filename=Path(finding.dossier_path).name)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as s:
        s.starttls()
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
        s.send_message(msg)
    return f"Emailed candidate to reviewer {config.REVIEWER_EMAIL} (for human decision)."


def _send_webhook(finding: Finding, draft: str) -> str:  # pragma: no cover - needs webhook URL
    import requests

    if not config.REVIEW_WEBHOOK:
        raise RuntimeError("Webhook transport needs RAQEEB_REVIEW_WEBHOOK.")
    resp = requests.post(config.REVIEW_WEBHOOK,
                         json={"text": draft, "finding": finding.to_dict()}, timeout=15)
    resp.raise_for_status()
    return f"Posted candidate to the review webhook ({resp.status_code})."
