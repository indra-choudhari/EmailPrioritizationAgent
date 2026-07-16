"""
email_agent/writer.py — Write report artifacts to reports/yyyymmdd/.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path


def write_reports(artifacts: dict[str, str], output_dir: str,
                  overwrite: bool = False,
                  scan_dt: datetime | None = None) -> list[str]:
    """Write HTML, JSON, and plain-text artifacts to reports/yyyymmdd/.

    Returns list of absolute paths written.
    Never overwrites existing files unless overwrite=True.
    """
    dt = scan_dt or datetime.now(timezone.utc)
    date_folder = dt.strftime("%Y%m%d")
    out_path = Path(output_dir) / date_folder
    out_path.mkdir(parents=True, exist_ok=True)

    ext_map = {"html": "email-triage.html",
               "json": "email-triage.json",
               "text": "email-triage.txt"}

    written = []
    for key, filename in ext_map.items():
        content = artifacts.get(key, "")
        if not content:
            continue

        target = out_path / filename
        if target.exists() and not overwrite:
            # Append timestamp suffix instead of overwriting
            ts = dt.strftime("%H%M%S")
            stem, suffix = filename.rsplit(".", 1)
            target = out_path / f"{stem}-{ts}.{suffix}"

        target.write_text(content, encoding="utf-8")
        written.append(str(target.resolve()))
        print(f"  → {target.resolve()}")

    return written
