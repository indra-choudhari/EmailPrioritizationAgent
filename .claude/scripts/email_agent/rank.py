"""
email_agent/rank.py — Priority tier assignment with SLA-floor rule.
"""
from __future__ import annotations
import re
from typing import Any


_TIER_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}

# Auto-generated replies (OOO, automatic responses) never need action from the
# reader, regardless of what keywords appear in their body text.
_AUTO_REPLY_RE = re.compile(
    r"^(automatic reply|auto[- ]?reply|automatic response|out of office)\s*:",
    re.IGNORECASE,
)

# Calendar RSVP notices carry no actionable content even when sent 1:1 — don't
# let the solo-recipient floor promote "Accepted: <meeting>" style subjects.
_CALENDAR_NOTICE_RE = re.compile(r"^(accepted|declined|tentative)\s*:", re.IGNORECASE)

# Internal comms/newsletter blasts are often personalized to a single named
# recipient ("Hey Indra, ...") from a human-looking @nice.com address, which
# would otherwise look identical to a genuine 1:1 colleague email.
_NEWSLETTER_SUBJECT_RE = re.compile(r"\b(newsletter|pulse|digest|bulletin)\b", re.IGNORECASE)

# Relationships that indicate a real, known human — as opposed to "external"
# (could be marketing sent to your address alone) or "unknown" (automated/bot).
_PERSONAL_SENDER_RELATIONSHIPS = {"frequent", "manager", "vip", "direct_report"}


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

    Both floors only fire when the email is genuinely, narrowly addressed to
    the reader (``directed`` and recipient_count <= keyword_floor_max_recipients)
    — a keyword like "critical" appearing in a status update on an 8-person
    team thread shouldn't outrank the reader's own actual to-do list. Automatic
    replies (OOO, auto-responses) are exempt from both floors and forced to P4:
    they never require action, no matter what keywords their body echoes back.

    Returns:
        {"P1": [...], "P2": [...], "P3": [...], "P4": [...]}
    """
    sla_keywords: list[str] = cfg.get("sla_floor_keywords", [])
    floor_max_recipients: int = cfg.get("keyword_floor_max_recipients", 5)

    sorted_emails = sorted(
        scored_emails, key=lambda e: e.get("urgency_score", 0), reverse=True
    )

    tiers: dict[str, list] = {"P1": [], "P2": [], "P3": [], "P4": []}
    for email in sorted_emails:
        if _is_auto_reply(email):
            email = {**email, "auto_reply": True, "priority_tier": "P4"}
            tiers["P4"].append(email)
            continue

        score = email.get("urgency_score", 0)
        tier = _assign_tier(score)

        floor_eligible = (
            email.get("directed")
            and email.get("recipient_count", 999) <= floor_max_recipients
        )

        # SLA-floor promotion (same-day deadline + score >= 50 → P1)
        if floor_eligible and tier in ("P2", "P3") and score >= 50:
            if _has_sla_keyword(email, sla_keywords):
                tier = "P1"
                email = {**email, "sla_promoted": True}

        # Keyword floor (e.g. "critical" → P1, "urgent" → P2), score-independent.
        if floor_eligible:
            floor_tier, matched_kw = _keyword_floor(email, cfg)
            if floor_tier and _TIER_RANK[floor_tier] < _TIER_RANK[tier]:
                tier = floor_tier
                email = {**email, "keyword_promoted": True, "promoted_by": matched_kw}

        # Onboarding floor: Product-Type / Telemetry onboarding requests are team
        # work — prioritize them even though they arrive from automated senders.
        # Still requires the reader to actually be a recipient of a narrowly-
        # addressed thread, not one of many on a broad status/report thread that
        # merely mentions an onboarding-shaped term (e.g. "prod_type_id") in passing.
        onboarding_eligible = (
            email.get("directed_to_me")
            and email.get("recipient_count", 999) <= floor_max_recipients
        )
        if onboarding_eligible and _is_onboarding(email, cfg):
            email = {**email, "onboarding": True}
            ob_tier = cfg.get("onboarding_floor_tier", "P2")
            if _TIER_RANK.get(ob_tier, 4) < _TIER_RANK[tier]:
                tier = ob_tier
                email = {**email, "onboarding_promoted": True}

        # Solo-recipient floor: a genuine 1:1 email from a known colleague is
        # itself the signal that it needs a look — even when the connector's
        # truncated body preview is too short to surface an action keyword
        # (e.g. a preview that cuts off after "Hi @Indra,"). Excludes calendar
        # RSVP notices and non-personal senders (automated/external/marketing).
        if _is_solo_direct_ask(email):
            solo_tier = cfg.get("solo_recipient_floor_tier", "P2")
            if _TIER_RANK.get(solo_tier, 4) < _TIER_RANK[tier]:
                tier = solo_tier
                email = {**email, "solo_recipient_promoted": True}

        email = {**email, "priority_tier": tier}
        tiers[tier].append(email)

    return tiers


def _is_auto_reply(email: dict) -> bool:
    """True for OOO / automatic-response messages, identified by subject
    prefix. These never need a reply regardless of body keywords."""
    subject = (email.get("subject") or "").strip()
    return bool(_AUTO_REPLY_RE.match(subject))


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


def _is_solo_direct_ask(email: dict) -> bool:
    """True when you are the ONLY recipient of an email from a known human
    colleague (not a calendar RSVP notice, not automated/external mail)."""
    if email.get("recipient_count") != 1 or not email.get("directed_to_me"):
        return False
    if email.get("sender_relationship") not in _PERSONAL_SENDER_RELATIONSHIPS:
        return False
    subject = (email.get("subject") or "").strip()
    if _CALENDAR_NOTICE_RE.match(subject) or _NEWSLETTER_SUBJECT_RE.search(subject):
        return False
    return True


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
