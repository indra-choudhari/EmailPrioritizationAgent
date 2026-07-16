"""
email_agent/recommend.py — Per-email action, reply tone, and effort estimate.
"""
from __future__ import annotations
import re
from typing import Any

_TIER_ACTION = {
    "P1": "Reply now",
    "P2": "Reply today",
    "P3": "Review when free",
    "P4": "Archive / no action",
}

_TIER_EFFORT = {
    "P1": "detailed",
    "P2": "medium",
    "P3": "quick",
    "P4": "none",
}


def recommend(email: dict[str, Any], cfg: dict) -> dict[str, Any]:
    """Add suggested_action, reply_tone, effort_estimate, and (for emails
    directed at the user) attn_kind/attn_reason to the email dict."""
    tier = email.get("priority_tier", "P4")
    suggested_action = _TIER_ACTION.get(tier, "Archive / no action")
    reply_tone = _reply_tone(email, cfg)
    effort = _effort(email, tier)
    attn_kind, attn_reason = _attention(email, suggested_action)

    return {
        **email,
        "suggested_action": suggested_action,
        "reply_tone": reply_tone,
        "effort_estimate": effort,
        "attn_kind": attn_kind,
        "attn_reason": attn_reason,
    }


def _attention(email: dict, suggested_action: str) -> tuple[str, str]:
    """Classify why a "Directed at You" email needs attention. Empty strings
    when the email isn't directed at the user (see ingest.load_emails)."""
    if not email.get("directed"):
        return "", ""

    subject = (email.get("subject") or "").strip()
    text = (subject + " " + (email.get("body_preview") or "")).lower()

    if suggested_action.startswith("Reply"):
        return "reply", "Reply needed"
    if re.match(r"^(canceled|cancelled)\s*:", subject, re.IGNORECASE):
        return "cancel", "Meeting cancelled"
    if "microsoft teams meeting" in text or re.search(
        r"\b(sync|cadence|ip week|standup|stand-up)\b", text
    ):
        return "meeting", "Team meeting / planning"
    if re.search(r"\b(achievement|release)\b", text):
        return "fyi", "FYI - team update"
    return "attn", "For your attention"


def _reply_tone(email: dict, cfg: dict) -> str:
    """Determine appropriate reply tone based on sender relationship and content."""
    empathy_kws: list[str] = cfg.get("empathy_keywords", [])
    text = (
        (email.get("subject") or "") + " " +
        (email.get("body_preview") or "")
    ).lower()

    # Check for emotional / empathy keywords first
    if any(kw.lower() in text for kw in empathy_kws):
        return "empathetic"

    relationship = email.get("sender_relationship", "unknown")
    if relationship in ("vip", "external"):
        return "formal"
    if relationship in ("manager",):
        return "formal"
    if relationship in ("direct_report", "frequent"):
        return "concise"

    tier = email.get("priority_tier", "P4")
    if tier == "P1":
        return "formal"
    return "concise"


def _effort(email: dict, tier: str) -> str:
    """Estimate reply effort based on tier, thread depth, and attachments."""
    if tier == "P4":
        return "none"

    base = _TIER_EFFORT.get(tier, "quick")

    # Bump up effort for long threads or attachments on P2/P3
    if tier in ("P2", "P3"):
        if email.get("has_attachments") or email.get("thread_depth", 1) >= 4:
            return "detailed"

    return base
