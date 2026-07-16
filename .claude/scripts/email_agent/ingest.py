"""
email_agent/ingest.py — Load emails from a Microsoft 365 connector dump.

Connector-only: emails are fetched by Claude via the Microsoft 365 connector
(`outlook_email_search`) and handed to this module as a JSON file. There is NO
Microsoft Graph HTTP call and NO MSAL token here — the connector is the sole
mail source.

Expected input: a JSON array of email objects as returned by the connector,
e.g.:
    [
      {
        "subject": "...",
        "sender": "alice@contoso.com",
        "receivedDateTime": "2026-07-15T06:35:50.000Z",
        "importance": "normal",
        "hasAttachments": false,
        "isRead": false,
        "summary": "first ~200 chars of the body",
        "id": "AAMk...",
        "webLink": "https://outlook.office365.com/...",
        "recipients": ["alice@contoso.com", "bob@contoso.com"]
      },
      ...
    ]

`recipients` drives the "directed at you" classification (see `directed`,
`directed_to_me`, `recipient_count` below) — a small, named-recipient list from
a real sender, distinct from a mass distribution/broadcast email.

Read-only: this module never sends, moves, or deletes anything.
Body preview capped at 200 characters.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_RE_PREFIX = re.compile(r"^\s*(re|fw|fwd)\s*:\s*", re.IGNORECASE)

# Substrings that mark an automated / no-reply / bulk sender → "unknown" authority
_AUTOMATED_MARKERS = (
    "noreply", "no-reply", "donotreply", "do-not-reply", "notification",
    "notifications", "jenkins", "automation", "alerts", "-bot", "mailer",
    "digest", "announcement", "communication", "365-noreply", "infratools",
    "facilities", "growpro", "innovation.", "life@", "opsnotify", "sharedmailbox",
)


def load_emails(input_path: str | Path, cfg: dict,
                since_hours: int | None = None,
                folder: str | None = None) -> list[dict[str, Any]]:
    """Load and normalize emails from a connector JSON dump.

    Args:
        input_path: Path to the JSON file written from the connector search.
        cfg: Loaded config dict.
        since_hours: Optional defensive look-back filter (drops older emails).
        folder: Informational only (the connector already scoped the search).

    Returns:
        List of RawEmail dicts matching the internal data contract consumed by
        extract.extract_signals().
    """
    raw = _read_dump(input_path)

    cutoff: datetime | None = None
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    user_email = (cfg.get("user_email") or "").strip().lower()
    directed_max = cfg.get("directed_recipient_max", 15)

    # First pass: normalize core fields
    normalized: list[dict[str, Any]] = []
    for msg in raw:
        received = _parse_dt(msg.get("receivedDateTime"))
        if cutoff and received < cutoff:
            continue
        sender = (msg.get("sender") or msg.get("from") or "").strip().lower()
        recipients = [
            r.strip().lower() for r in (msg.get("recipients") or [])
            if isinstance(r, str) and r.strip()
        ]
        normalized.append({
            "id": msg.get("id", ""),
            "subject": msg.get("subject") or "(no subject)",
            "from_email": sender,
            "from_name": _display_name(sender),
            "received_at": received,
            "importance": (msg.get("importance") or "normal"),
            "has_attachments": bool(msg.get("hasAttachments")),
            "body_preview": (msg.get("summary") or msg.get("bodyPreview") or "")[:200],
            "is_read": bool(msg.get("isRead")),
            "web_link": msg.get("webLink", ""),
            "recipient_count": len(recipients),
            "directed_to_me": bool(user_email) and user_email in recipients,
            "_norm_subject": _normalize_subject(msg.get("subject") or ""),
        })

    # Second pass: thread depth = count of emails sharing a normalized subject
    depth: dict[str, int] = {}
    for e in normalized:
        depth[e["_norm_subject"]] = depth.get(e["_norm_subject"], 0) + 1

    for e in normalized:
        e["conversation_id"] = e["_norm_subject"]
        e["thread_depth"] = depth.get(e["_norm_subject"], 1)
        e["sender_relationship"] = _classify_sender(e["from_email"], cfg)
        # "Directed at you": named recipient of a small (non-broadcast) list
        # from a real (non-automated) sender — never a mass distribution list.
        e["directed"] = (
            e["directed_to_me"]
            and e["recipient_count"] <= directed_max
            and e["sender_relationship"] != "unknown"
        )
        del e["_norm_subject"]

    return normalized


# ── input parsing ────────────────────────────────────────────────────────────

def _read_dump(input_path: str | Path) -> list[dict]:
    """Read the connector dump. Accepts a clean JSON array, or an object with an
    'emails'/'value' array."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Connector dump not found: {path}. "
            "Fetch emails via the Microsoft 365 connector and write them to this file."
        )
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("emails", "value", "results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError(
        "Connector dump must be a JSON array of email objects "
        "(or an object with an 'emails' array)."
    )


# ── field helpers ──────────────────────────────────────────────────────────—

def _normalize_subject(subject: str) -> str:
    s = subject or ""
    prev = None
    while s != prev:
        prev = s
        s = _RE_PREFIX.sub("", s)
    return s.strip().lower()


def _display_name(email: str) -> str:
    """Best-effort human name from an address (connector gives no display name)."""
    if not email or "@" not in email:
        return email or "(unknown)"
    local = email.split("@", 1)[0]
    if any(m in email for m in _AUTOMATED_MARKERS):
        return email  # keep automated addresses verbatim
    parts = re.split(r"[._-]+", local)
    parts = [p for p in parts if p and not p.isdigit()]
    if not parts:
        return email
    return " ".join(p.capitalize() for p in parts)


def _classify_sender(email: str, cfg: dict) -> str:
    """Heuristic sender relationship (People.Read is unavailable via the connector).

    vip / manager come from config; everything else is inferred from the address:
      - automated / no-reply / bulk markers            → unknown
      - internal domain + human-looking name           → frequent
      - external domain                                → external
      - otherwise                                      → unknown
    """
    e = (email or "").lower()
    if not e:
        return "unknown"
    if e in {v.lower() for v in cfg.get("vip_senders", [])}:
        return "vip"
    if e in {m.lower() for m in cfg.get("manager_emails", [])}:
        return "manager"

    if any(m in e for m in _AUTOMATED_MARKERS):
        return "unknown"

    local, _, domain = e.partition("@")
    internal_domains = [d.lower() for d in cfg.get("internal_domains", ["nice.com"])]
    is_internal = any(domain == d or domain.endswith("." + d) for d in internal_domains)
    # firstname.lastname style (a trailing disambiguation digit like "patil3" is fine;
    # automated/bulk addresses are already excluded by _AUTOMATED_MARKERS above)
    looks_like_person = "." in local

    if is_internal and looks_like_person:
        return "frequent"
    if not is_internal:
        return "external"
    return "unknown"


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
