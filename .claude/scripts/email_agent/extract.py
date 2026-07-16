"""
email_agent/extract.py — Extract scoring signals from a RawEmail dict.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any

# Recency thresholds (hours)
_VERY_RECENT_H = 2
_RECENT_H = 8
_TODAY_H = 24

# Authority scores by relationship tier
_AUTHORITY = {
    "vip": 100,
    "manager": 80,
    "direct_report": 70,
    "frequent": 55,
    "external": 30,
    "unknown": 10,
}


def extract_signals(email: dict[str, Any], cfg: dict) -> dict[str, float]:
    """Derive the 6 scoring signals from a RawEmail dict.

    Returns SignalVector: dict with keys matching config['weights'].
    """
    return {
        "sender_authority": _sender_authority(email, cfg),
        "action_language": _action_language(email, cfg),
        "recency": _recency(email),
        "thread_depth": _thread_depth(email),
        "importance_flag": _importance_flag(email),
        "has_attachment": _attachment(email),
    }


# ── individual signal functions ─────────────────────────────────────────────

def _sender_authority(email: dict, cfg: dict) -> float:
    rel = email.get("sender_relationship", "unknown")
    return float(_AUTHORITY.get(rel, 10))


def _action_language(email: dict, cfg: dict) -> float:
    keywords: list[str] = cfg.get("high_priority_keywords", [])
    if not keywords:
        return 0.0

    text = (
        (email.get("subject") or "") + " " +
        (email.get("body_preview") or "")
    ).lower()

    hits = sum(1 for kw in keywords if kw.lower() in text)
    # Normalize: 3+ hits → 100, linear below that
    normalized = min(hits / 3.0, 1.0) * 100
    return round(normalized, 1)


def _recency(email: dict) -> float:
    received: datetime = email.get("received_at")
    if not received:
        return 10.0
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)

    age_hours = (datetime.now(timezone.utc) - received).total_seconds() / 3600

    if age_hours <= _VERY_RECENT_H:
        return 100.0
    if age_hours <= _RECENT_H:
        return 70.0
    if age_hours <= _TODAY_H:
        return 40.0
    return 10.0


def _thread_depth(email: dict) -> float:
    depth = email.get("thread_depth", 1)
    # Normalize: 5+ replies → 100
    return round(min(depth / 5.0, 1.0) * 100, 1)


def _importance_flag(email: dict) -> float:
    importance = (email.get("importance") or "normal").lower()
    if importance == "high":
        return 100.0
    if importance == "normal":
        return 30.0
    return 0.0  # "low"


def _attachment(email: dict) -> float:
    return 100.0 if email.get("has_attachments") else 0.0
