"""
email_agent/rank.py — Priority tier assignment with SLA-floor rule.
"""
from __future__ import annotations
from typing import Any


_TIER_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def rank_emails(scored_emails: list[dict[str, Any]],
                cfg: dict) -> dict[str, list[dict]]:
    """Assign P1–P4 tiers and return tier-grouped result.

    Two floor rules can promote an email above its raw score-based tier:

    1. Keyword floor (``priority_keyword_floors``): if subject/body_preview
       contains a configured keyword, the tier is floored to that keyword's
       tier — e.g. "critical" → P1, "urgent" → P2 — regardless of score. A floor
       only ever raises priority, never lowers it.
    2. SLA floor (``sla_floor_keywords``): if the text contains a same-day
       deadline keyword AND urgency_score >= 50, the email is promoted to P1.

    Returns:
        {"P1": [...], "P2": [...], "P3": [...], "P4": [...]}
    """
    sla_keywords: list[str] = cfg.get("sla_floor_keywords", [])

    sorted_emails = sorted(
        scored_emails, key=lambda e: e.get("urgency_score", 0), reverse=True
    )

    tiers: dict[str, list] = {"P1": [], "P2": [], "P3": [], "P4": []}
    for email in sorted_emails:
        score = email.get("urgency_score", 0)
        tier = _assign_tier(score)

        # SLA-floor promotion (same-day deadline + score >= 50 → P1)
        if tier in ("P2", "P3") and score >= 50:
            if _has_sla_keyword(email, sla_keywords):
                tier = "P1"
                email = {**email, "sla_promoted": True}

        # Keyword floor (e.g. "critical" → P1, "urgent" → P2), score-independent.
        floor_tier, matched_kw = _keyword_floor(email, cfg)
        if floor_tier and _TIER_RANK[floor_tier] < _TIER_RANK[tier]:
            tier = floor_tier
            email = {**email, "keyword_promoted": True, "promoted_by": matched_kw}

        # Onboarding floor: Product-Type / Telemetry onboarding requests are team
        # work — prioritize them even though they arrive from automated senders.
        if _is_onboarding(email, cfg):
            email = {**email, "onboarding": True}
            ob_tier = cfg.get("onboarding_floor_tier", "P2")
            if _TIER_RANK.get(ob_tier, 4) < _TIER_RANK[tier]:
                tier = ob_tier
                email = {**email, "onboarding_promoted": True}

        email = {**email, "priority_tier": tier}
        tiers[tier].append(email)

    return tiers


def _keyword_floor(email: dict, cfg: dict) -> tuple[str | None, str | None]:
    """Return (tier, matched_keyword) if the text matches a priority-floor
    keyword, else (None, None). More urgent tiers are checked first, so the
    most severe matching floor wins."""
    floors: dict = cfg.get("priority_keyword_floors", {})
    text = (
        (email.get("subject") or "") + " " +
        (email.get("body_preview") or "")
    ).lower()
    for tier in ("P1", "P2", "P3"):
        for kw in floors.get(tier, []):
            if kw.lower() in text:
                return tier, kw
    return None, None


def _is_onboarding(email: dict, cfg: dict) -> bool:
    """Detect a Product-Type / Telemetry onboarding request. Subject keywords
    match on the subject only (to avoid newsletters that merely mention
    'onboarding' in the body); text keywords match subject + body."""
    subject = (email.get("subject") or "").lower()
    text = subject + " " + (email.get("body_preview") or "").lower()
    for kw in cfg.get("onboarding_subject_keywords", []):
        if kw.lower() in subject:
            return True
    for kw in cfg.get("onboarding_text_keywords", []):
        if kw.lower() in text:
            return True
    return False


def _assign_tier(score: float) -> str:
    if score >= 80:
        return "P1"
    if score >= 55:
        return "P2"
    if score >= 30:
        return "P3"
    return "P4"


def _has_sla_keyword(email: dict, keywords: list[str]) -> bool:
    text = (
        (email.get("subject") or "") + " " +
        (email.get("body_preview") or "")
    ).lower()
    return any(kw.lower() in text for kw in keywords)
