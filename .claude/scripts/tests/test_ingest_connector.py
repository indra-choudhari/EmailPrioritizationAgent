"""
tests/test_ingest_connector.py — Unit tests for the connector-fed ingest module.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_agent import ingest

_CFG = {
    "internal_domains": ["nice.com", "niceincontact.com"],
    "vip_senders": ["ceo@nice.com"],
    "manager_emails": ["boss@nice.com"],
    "user_email": "me@nice.com",
    "directed_recipient_max": 15,
}


def _write(tmp, emails):
    p = Path(tmp) / "dump.json"
    p.write_text(json.dumps(emails), encoding="utf-8")
    return p


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _msg(sender, subject="Hello", hours_ago=1, **kw):
    m = {"sender": sender, "subject": subject, "receivedDateTime": _iso(hours_ago),
         "importance": "normal", "hasAttachments": False, "isRead": False,
         "summary": kw.get("summary", "body"), "id": kw.get("id", "x")}
    m.update({k: v for k, v in kw.items() if k not in ("summary", "id")})
    return m


# ── sender classification ─────────────────────────────────────────────────────

def test_vip_from_config(tmp_path):
    p = _write(tmp_path, [_msg("ceo@nice.com")])
    e = ingest.load_emails(p, _CFG)[0]
    assert e["sender_relationship"] == "vip"


def test_manager_from_config(tmp_path):
    p = _write(tmp_path, [_msg("boss@nice.com")])
    assert ingest.load_emails(p, _CFG)[0]["sender_relationship"] == "manager"


def test_internal_person_is_frequent(tmp_path):
    p = _write(tmp_path, [_msg("yogesh.patil3@nice.com")])
    assert ingest.load_emails(p, _CFG)[0]["sender_relationship"] == "frequent"


def test_automated_is_unknown(tmp_path):
    for addr in ("noreply-alerts@opsnotify.nicecxone.uk",
                 "cxone-ci.jenkins@devops.niceincontact.com",
                 "365-noreply@nice.com"):
        p = _write(tmp_path, [_msg(addr)])
        assert ingest.load_emails(p, _CFG)[0]["sender_relationship"] == "unknown", addr


def test_external_domain(tmp_path):
    p = _write(tmp_path, [_msg("alice@contoso.com")])
    assert ingest.load_emails(p, _CFG)[0]["sender_relationship"] == "external"


# ── thread depth ──────────────────────────────────────────────────────────────

def test_thread_depth_groups_by_normalized_subject(tmp_path):
    p = _write(tmp_path, [
        _msg("a.b@nice.com", subject="Dependency on BIL-8533"),
        _msg("c.d@nice.com", subject="RE: Dependency on BIL-8533"),
        _msg("e.f@nice.com", subject="Fw: Dependency on BIL-8533"),
    ])
    emails = ingest.load_emails(p, _CFG)
    assert all(e["thread_depth"] == 3 for e in emails)


# ── window filter ─────────────────────────────────────────────────────────────

def test_since_hours_filters_old(tmp_path):
    p = _write(tmp_path, [_msg("a.b@nice.com", hours_ago=1),
                          _msg("c.d@nice.com", hours_ago=100)])
    emails = ingest.load_emails(p, _CFG, since_hours=24)
    assert len(emails) == 1


# ── field mapping / robustness ────────────────────────────────────────────────

def test_body_preview_capped_at_200(tmp_path):
    p = _write(tmp_path, [_msg("a.b@nice.com", summary="x" * 500)])
    assert len(ingest.load_emails(p, _CFG)[0]["body_preview"]) == 200


def test_accepts_object_with_emails_key(tmp_path):
    path = Path(tmp_path) / "d.json"
    path.write_text(json.dumps({"emails": [_msg("a.b@nice.com")]}), encoding="utf-8")
    assert len(ingest.load_emails(path, _CFG)) == 1


def test_missing_file_raises(tmp_path):
    try:
        ingest.load_emails(Path(tmp_path) / "nope.json", _CFG)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


# ── "directed at you" classification ─────────────────────────────────────────

def test_directed_small_group_with_me(tmp_path):
    """User named as recipient in a small (<=15) list from a real sender → directed."""
    p = _write(tmp_path, [_msg(
        "a.b@nice.com", recipients=["me@nice.com", "c.d@nice.com", "e.f@nice.com"]
    )])
    e = ingest.load_emails(p, _CFG)[0]
    assert e["directed_to_me"] is True
    assert e["recipient_count"] == 3
    assert e["directed"] is True


def test_not_directed_large_broadcast(tmp_path):
    """User named as recipient but the list is a mass distribution (>15) → not directed."""
    recipients = ["me@nice.com"] + [f"user{i}@nice.com" for i in range(20)]
    p = _write(tmp_path, [_msg("a.b@nice.com", recipients=recipients)])
    e = ingest.load_emails(p, _CFG)[0]
    assert e["directed_to_me"] is True
    assert e["recipient_count"] == 21
    assert e["directed"] is False


def test_not_directed_when_user_absent(tmp_path):
    """User is not in the recipient list at all → not directed, regardless of size."""
    p = _write(tmp_path, [_msg(
        "a.b@nice.com", recipients=["c.d@nice.com", "e.f@nice.com"]
    )])
    e = ingest.load_emails(p, _CFG)[0]
    assert e["directed_to_me"] is False
    assert e["directed"] is False


def test_not_directed_automated_sender(tmp_path):
    """Small named-recipient list, but the sender is automated/bulk → not directed."""
    p = _write(tmp_path, [_msg(
        "noreply-alerts@opsnotify.nicecxone.uk",
        recipients=["me@nice.com", "c.d@nice.com"],
    )])
    e = ingest.load_emails(p, _CFG)[0]
    assert e["directed_to_me"] is True
    assert e["sender_relationship"] == "unknown"
    assert e["directed"] is False


def test_no_recipients_field_is_safe(tmp_path):
    """Missing 'recipients' key entirely must not crash — just not directed."""
    p = _write(tmp_path, [_msg("a.b@nice.com")])
    e = ingest.load_emails(p, _CFG)[0]
    assert e["recipient_count"] == 0
    assert e["directed"] is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
