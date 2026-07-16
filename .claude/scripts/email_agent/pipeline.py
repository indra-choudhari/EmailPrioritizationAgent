"""
email_agent/pipeline.py — Wire the scoring skills into the triage pipeline.

Connector-only: mail is supplied as a JSON dump produced from the Microsoft 365
connector (see ingest.load_emails). No auth step, no Microsoft Graph.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ingest, extract, score, rank, recommend, report, writer


def run(cfg: dict, input_path: str, since_hours: int | None = None,
        folder: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    """Execute the triage pipeline over a connector dump.

    Skills: ingest → extract → score → rank → recommend → report → write

    Returns:
        result dict with keys: tiered, meta, artifacts, paths_written
    """
    t0 = time.time()
    scan_dt = datetime.now(timezone.utc)
    incomplete = False
    incomplete_reason = ""
    emails_raw = []

    # 1. Ingest (from the connector JSON dump)
    try:
        emails_raw = ingest.load_emails(
            input_path, cfg,
            since_hours=since_hours,
            folder=folder,
        )
    except Exception as exc:
        incomplete = True
        incomplete_reason = str(exc)
        emails_raw = []

    # 2–5. Extract → Score → Rank → Recommend
    scored_emails = []
    for email in emails_raw:
        try:
            signals = extract.extract_signals(email, cfg)
            scored = {**email, **score.score_email(signals, cfg)}
            scored_emails.append(scored)
        except Exception as exc:
            incomplete = True
            incomplete_reason = f"Scoring error on '{email.get('subject','')}': {exc}"

    tiered = rank.rank_emails(scored_emails, cfg)

    recommended_tiered: dict[str, list] = {}
    for tier_key, tier_emails in tiered.items():
        recommended_tiered[tier_key] = [
            recommend.recommend(e, cfg) for e in tier_emails
        ]

    # 6. Report
    meta = {
        "folder": folder or cfg.get("folder", "Inbox"),
        "since_hours": since_hours if since_hours is not None else cfg.get("since_hours", 24),
        "total_count": len(emails_raw),
        "run_time_s": round(time.time() - t0, 1),
        "scan_dt": scan_dt,
        "incomplete": incomplete,
        "incomplete_reason": incomplete_reason,
        "source": "microsoft-365-connector",
        "user_display_name": ingest._display_name(cfg.get("user_email", "")),
    }
    output_dir = cfg.get("output_dir", "./reports")
    drafts = _load_drafts(output_dir, scan_dt)
    artifacts = report.build_report(recommended_tiered, meta, drafts=drafts)

    # 7. Write
    paths = writer.write_reports(artifacts, output_dir,
                                 overwrite=overwrite, scan_dt=scan_dt)

    return {
        "tiered": recommended_tiered,
        "meta": meta,
        "artifacts": artifacts,
        "paths_written": paths,
    }


def _load_drafts(output_dir: str, scan_dt: datetime) -> dict[str, dict]:
    """Best-effort load of reports/<yyyymmdd>/drafts.json, written by the
    `Draft replies` agent. Missing or unreadable is not an error — the
    dashboard just shows no draft-ready state."""
    path = Path(output_dir) / scan_dt.strftime("%Y%m%d") / "drafts.json"
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
