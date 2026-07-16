"""
email_agent/score.py — Weighted urgency scoring.
"""
from __future__ import annotations
from typing import Any


def score_email(signals: dict[str, float], cfg: dict) -> dict[str, Any]:
    """Apply weighted scoring to a SignalVector.

    Returns ScoredEmail additions:
        urgency_score   : float  0–100
        top_3_signals   : list[dict]  [{name, weighted_contribution}]
        confidence      : "high" | "medium" | "low"
    """
    weights: dict[str, float] = cfg["weights"]

    contributions = {
        key: round(weights.get(key, 0) * signals.get(key, 0), 2)
        for key in weights
    }

    urgency_score = round(sum(contributions.values()), 1)

    # Top-3 by weighted contribution (descending)
    top_3 = sorted(contributions.items(), key=lambda x: x[1], reverse=True)[:3]
    top_3_signals = [{"signal": name, "contribution": val} for name, val in top_3]

    # Confidence
    non_zero = sum(1 for v in signals.values() if v > 0)
    sender_known = signals.get("sender_authority", 10) > 10
    has_keywords = signals.get("action_language", 0) > 0

    if non_zero >= 3 and sender_known:
        confidence = "high"
    elif non_zero >= 2 or has_keywords:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "urgency_score": urgency_score,
        "top_3_signals": top_3_signals,
        "confidence": confidence,
    }
