"""
tests/test_scoring_pipeline.py — Unit tests for extract, score, rank, recommend, report.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_agent.extract import extract_signals
from email_agent.score import score_email
from email_agent.rank import rank_emails
from email_agent.recommend import recommend
from email_agent.report import build_report

# ── Fixtures ────────────────────────────────────────────────────────────────

_BASE_CFG = {
    "tenant_id": "t",
    "client_id": "c",
    "vip_senders": ["ceo@corp.com"],
    "manager_emails": ["mgr@corp.com"],
    "high_priority_keywords": ["urgent", "action required", "P0", "ASAP", "by EOD"],
    "sla_floor_keywords": ["by EOD", "by end of day", "today"],
    "empathy_keywords": ["concern", "frustrated", "complaint"],
    "weights": {
        "sender_authority": 0.30,
        "action_language": 0.25,
        "recency": 0.20,
        "thread_depth": 0.10,
        "importance_flag": 0.10,
        "has_attachment": 0.05,
    },
}

_NOW = datetime.now(timezone.utc)


def _email(subject="Hello", from_email="peer@corp.com", from_name="Peer",
           relationship="frequent", importance="normal", has_att=False,
           body_preview="", thread_depth=1, hours_ago=1):
    return {
        "id": "msg1",
        "subject": subject,
        "from_name": from_name,
        "from_email": from_email,
        "received_at": _NOW - timedelta(hours=hours_ago),
        "importance": importance,
        "has_attachments": has_att,
        "conversation_id": "conv1",
        "body_preview": body_preview[:200],
        "is_read": False,
        "sender_relationship": relationship,
        "thread_depth": thread_depth,
    }


# ── extract_signals ──────────────────────────────────────────────────────────

def test_vip_sender_authority():
    email = _email(from_email="ceo@corp.com", relationship="vip")
    signals = extract_signals(email, _BASE_CFG)
    assert signals["sender_authority"] == 100.0


def test_unknown_sender_authority():
    email = _email(relationship="unknown")
    signals = extract_signals(email, _BASE_CFG)
    assert signals["sender_authority"] == 10.0


def test_action_keyword_in_subject():
    email = _email(subject="URGENT: deploy now")
    signals = extract_signals(email, _BASE_CFG)
    assert signals["action_language"] > 0


def test_no_keywords_action_zero():
    email = _email(subject="Weekly newsletter", body_preview="Here is this week's update.")
    signals = extract_signals(email, _BASE_CFG)
    assert signals["action_language"] == 0.0


def test_very_recent_recency():
    email = _email(hours_ago=0.5)
    signals = extract_signals(email, _BASE_CFG)
    assert signals["recency"] == 100.0


def test_old_email_low_recency():
    email = _email(hours_ago=48)
    signals = extract_signals(email, _BASE_CFG)
    assert signals["recency"] == 10.0


def test_attachment_signal():
    email = _email(has_att=True)
    signals = extract_signals(email, _BASE_CFG)
    assert signals["has_attachment"] == 100.0


def test_no_attachment_signal():
    email = _email(has_att=False)
    signals = extract_signals(email, _BASE_CFG)
    assert signals["has_attachment"] == 0.0


# ── score_email ──────────────────────────────────────────────────────────────

def test_score_vip_urgent_recent():
    email = _email(subject="URGENT: system down", relationship="vip", hours_ago=0.5)
    signals = extract_signals(email, _BASE_CFG)
    scored = score_email(signals, _BASE_CFG)
    assert scored["urgency_score"] >= 80
    assert len(scored["top_3_signals"]) == 3


def test_score_newsletter_low():
    email = _email(subject="Weekly digest", relationship="unknown", hours_ago=20)
    signals = extract_signals(email, _BASE_CFG)
    scored = score_email(signals, _BASE_CFG)
    assert scored["urgency_score"] < 30


def test_weights_sum_check():
    weights = _BASE_CFG["weights"]
    assert abs(sum(weights.values()) - 1.0) < 0.01


def test_top3_correctly_ordered():
    email = _email(subject="URGENT action required ASAP", relationship="vip",
                   importance="high", hours_ago=0.5, has_att=True)
    signals = extract_signals(email, _BASE_CFG)
    scored = score_email(signals, _BASE_CFG)
    contribs = [s["contribution"] for s in scored["top_3_signals"]]
    assert contribs == sorted(contribs, reverse=True)


# ── rank_emails ──────────────────────────────────────────────────────────────

def _scored_email(score_val, subject="Test", relationship="unknown", body=""):
    email = _email(subject=subject, relationship=relationship, body_preview=body,
                   hours_ago=2)
    signals = extract_signals(email, _BASE_CFG)
    sc = score_email(signals, _BASE_CFG)
    sc["urgency_score"] = score_val  # override for tier testing
    return {**email, **sc}


def test_rank_p1_threshold():
    emails = [_scored_email(85)]
    tiered = rank_emails(emails, _BASE_CFG)
    assert len(tiered["P1"]) == 1


def test_rank_p4_threshold():
    emails = [_scored_email(10)]
    tiered = rank_emails(emails, _BASE_CFG)
    assert len(tiered["P4"]) == 1


def test_sla_floor_promotes_p2_to_p1():
    """A score-62 email with 'by EOD' must be promoted to P1."""
    emails = [_scored_email(62, subject="Budget review by EOD")]
    tiered = rank_emails(emails, _BASE_CFG)
    assert len(tiered["P1"]) == 1
    assert tiered["P1"][0].get("sla_promoted") is True


def test_sla_floor_does_not_promote_below_50():
    """A score-45 email with 'by EOD' must NOT be promoted (below 50 floor threshold)."""
    emails = [_scored_email(45, subject="FYI by EOD")]
    tiered = rank_emails(emails, _BASE_CFG)
    assert len(tiered["P1"]) == 0


# ── keyword-floor rule (urgent → P2, critical → P1) ───────────────────────────

_KW_CFG = {**_BASE_CFG, "priority_keyword_floors": {"P1": ["critical"], "P2": ["urgent"]}}


def test_urgent_keyword_floors_to_p2():
    """A low-scoring email containing 'urgent' must be floored to at least P2."""
    emails = [_scored_email(20, subject="urgent : need help")]
    tiered = rank_emails(emails, _KW_CFG)
    assert len(tiered["P2"]) == 1
    assert tiered["P2"][0].get("keyword_promoted") is True
    assert tiered["P2"][0].get("promoted_by") == "urgent"


def test_critical_keyword_floors_to_p1():
    """'critical' anywhere in subject/body floors to P1, regardless of score."""
    emails = [_scored_email(16, subject="Reminder", body="this is a critical step")]
    tiered = rank_emails(emails, _KW_CFG)
    assert len(tiered["P1"]) == 1
    assert tiered["P1"][0].get("promoted_by") == "critical"


def test_keyword_floor_never_downgrades():
    """A genuine P1 (score 90) with 'urgent' stays P1 — the floor only raises."""
    emails = [_scored_email(90, subject="urgent")]
    tiered = rank_emails(emails, _KW_CFG)
    assert len(tiered["P1"]) == 1


def test_no_keyword_no_floor():
    """Without a floor keyword, tier follows the score."""
    emails = [_scored_email(16, subject="weekly newsletter")]
    tiered = rank_emails(emails, _KW_CFG)
    assert len(tiered["P4"]) == 1


# ── recommend ────────────────────────────────────────────────────────────────

def test_p1_external_formal_reply_now():
    email = {**_email(relationship="external"), "priority_tier": "P1",
             "urgency_score": 85, "top_3_signals": [], "confidence": "high"}
    rec = recommend(email, _BASE_CFG)
    assert rec["suggested_action"] == "Reply now"
    assert rec["reply_tone"] == "formal"


def test_p4_archive_no_action():
    email = {**_email(relationship="unknown"), "priority_tier": "P4",
             "urgency_score": 10, "top_3_signals": [], "confidence": "low"}
    rec = recommend(email, _BASE_CFG)
    assert rec["suggested_action"] == "Archive / no action"
    assert rec["effort_estimate"] == "none"


def test_empathy_tone():
    email = {**_email(subject="I'm frustrated with the process", relationship="external"),
             "priority_tier": "P2", "urgency_score": 60,
             "top_3_signals": [], "confidence": "medium"}
    rec = recommend(email, _BASE_CFG)
    assert rec["reply_tone"] == "empathetic"


# ── attn_kind / attn_reason (Directed at You) ────────────────────────────────

def test_not_directed_has_no_attn():
    """An email that isn't 'directed' gets empty attn_kind/attn_reason regardless of tier."""
    email = {**_email(relationship="frequent"), "priority_tier": "P1",
             "urgency_score": 85, "top_3_signals": [], "confidence": "high",
             "directed": False}
    rec = recommend(email, _BASE_CFG)
    assert rec["attn_kind"] == ""
    assert rec["attn_reason"] == ""


def test_directed_reply_needed():
    """Directed + a Reply-tier suggested_action → attn_kind 'reply'."""
    email = {**_email(relationship="frequent"), "priority_tier": "P1",
             "urgency_score": 85, "top_3_signals": [], "confidence": "high",
             "directed": True}
    rec = recommend(email, _BASE_CFG)
    assert rec["attn_kind"] == "reply"
    assert rec["attn_reason"] == "Reply needed"


def test_directed_cancelled_meeting():
    email = {**_email(subject="Canceled: Weekly Sync", relationship="frequent"),
             "priority_tier": "P3", "urgency_score": 40,
             "top_3_signals": [], "confidence": "medium", "directed": True}
    rec = recommend(email, _BASE_CFG)
    assert rec["attn_kind"] == "cancel"
    assert rec["attn_reason"] == "Meeting cancelled"


def test_directed_meeting_invite():
    email = {**_email(subject="Team Cadence", body_preview="Microsoft Teams meeting\nJoin",
                      relationship="frequent"),
             "priority_tier": "P3", "urgency_score": 35,
             "top_3_signals": [], "confidence": "medium", "directed": True}
    rec = recommend(email, _BASE_CFG)
    assert rec["attn_kind"] == "meeting"


def test_directed_fyi_fallback():
    email = {**_email(subject="Random update", relationship="frequent"),
             "priority_tier": "P4", "urgency_score": 20,
             "top_3_signals": [], "confidence": "low", "directed": True}
    rec = recommend(email, _BASE_CFG)
    assert rec["attn_kind"] == "attn"
    assert rec["attn_reason"] == "For your attention"


# ── build_report ─────────────────────────────────────────────────────────────

def _make_tiered(n_p1=1, n_p2=2, n_p3=3, n_p4=5):
    def _rec(tier, i):
        e = _email(subject=f"{tier} email {i}", relationship="frequent")
        signals = extract_signals(e, _BASE_CFG)
        sc = score_email(signals, _BASE_CFG)
        e2 = {**e, **sc, "priority_tier": tier,
              "suggested_action": "Reply now", "reply_tone": "concise",
              "effort_estimate": "quick"}
        return e2

    return {
        "P1": [_rec("P1", i) for i in range(n_p1)],
        "P2": [_rec("P2", i) for i in range(n_p2)],
        "P3": [_rec("P3", i) for i in range(n_p3)],
        "P4": [_rec("P4", i) for i in range(n_p4)],
    }


def _meta(total=11):
    return {"folder": "Inbox", "since_hours": 24, "total_count": total,
            "run_time_s": 1.2, "scan_dt": _NOW, "incomplete": False,
            "incomplete_reason": ""}


def test_full_report_has_all_keys():
    artifacts = build_report(_make_tiered(), _meta())
    assert "html" in artifacts
    assert "json" in artifacts
    assert "text" in artifacts


def test_json_is_valid():
    artifacts = build_report(_make_tiered(), _meta())
    data = json.loads(artifacts["json"])
    assert "tiers" in data
    assert "P1" in data["tiers"]


def test_inbox_clear_variant():
    artifacts = build_report({"P1": [], "P2": [], "P3": [], "P4": []},
                             _meta(total=0))
    assert "Inbox clear" in artifacts["html"]
    assert "no action required" in artifacts["text"].lower()


def test_incomplete_scan_banner():
    meta = {**_meta(), "incomplete": True, "incomplete_reason": "Network timeout"}
    artifacts = build_report(_make_tiered(), meta)
    assert "Incomplete scan" in artifacts["html"]


def test_text_digest_p1_p2_only():
    artifacts = build_report(_make_tiered(n_p1=2, n_p2=3), _meta())
    text = artifacts["text"]
    assert "P1" in text
    assert "P2" in text


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
