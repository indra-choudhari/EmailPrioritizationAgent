#!/usr/bin/env python3
"""
prioritize_emails.py — CLI entry point for EmailPrioritizationAgent (connector mode).

Mail is fetched by Claude via the Microsoft 365 connector and written to a JSON
dump; this script scores/ranks/reports that dump. There is no auth step here.

Usage:
    python prioritize_emails.py --input emails.json                 # score a dump
    python prioritize_emails.py --input emails.json --since 2d      # + look-back filter
    python prioritize_emails.py --input emails.json --digest        # P1+P2 digest to stdout
    python prioritize_emails.py --input emails.json --folder Focused # folder label (metadata)
    python prioritize_emails.py --input emails.json --overwrite      # overwrite today's report
    python prioritize_emails.py --input emails.json --config my-config.json
"""
from __future__ import annotations
import argparse
import sys
import traceback
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows consoles default to cp1252 and choke on the report's Unicode
# (arrows, check marks, emoji). Force UTF-8 output where supported.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from email_agent import pipeline
from email_agent.config import load_config


def parse_since(value: str) -> int:
    """Parse '2d', '4h', '30m' → hours (int)."""
    value = value.strip().lower()
    if value.endswith("d"):
        return int(value[:-1]) * 24
    if value.endswith("h"):
        return int(value[:-1])
    if value.endswith("m"):
        return max(1, int(value[:-1]) // 60)
    raise argparse.ArgumentTypeError(
        f"Invalid --since value '{value}'. Use formats like '2d', '4h', '90m'."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="EmailPrioritizationAgent — score a Microsoft 365 connector email dump."
    )
    parser.add_argument("--input", type=str, required=True,
                        help="Path to the connector email dump (JSON array). Required.")
    parser.add_argument("--since", type=str, default=None,
                        help="Defensive look-back filter, e.g. '2d', '4h' (default: config since_hours)")
    parser.add_argument("--folder", type=str, default=None,
                        help="Folder label for the report (default: config folder)")
    parser.add_argument("--digest", action="store_true",
                        help="Morning digest mode: print P1+P2 to stdout (last 18 h)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing report for today instead of timestamping")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config JSON (default: config.json in agent folder)")
    args = parser.parse_args()

    # Load config
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"✗ Config error: {exc}", file=sys.stderr)
        return 1

    # Resolve since_hours
    since_hours: int | None = None
    if args.since:
        try:
            since_hours = parse_since(args.since)
        except argparse.ArgumentTypeError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
    elif args.digest:
        since_hours = 18

    # Run pipeline
    try:
        result = pipeline.run(
            cfg,
            input_path=args.input,
            since_hours=since_hours,
            folder=args.folder,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        _write_error_report(cfg, exc)
        print(f"✗ Pipeline failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    # Print summary
    tiered = result["tiered"]
    counts = {t: len(tiered.get(t, [])) for t in ("P1", "P2", "P3", "P4")}
    html_path = next(
        (p for p in result["paths_written"] if p.endswith(".html")), "—"
    )

    print(
        f"\n✓ Triage complete — "
        f"{counts['P1']} P1, {counts['P2']} P2, "
        f"{counts['P3']} P3, {counts['P4']} P4.  "
        f"Report: {html_path}"
    )

    if result["meta"].get("incomplete"):
        print(f"  ⚠️  Incomplete scan: {result['meta'].get('incomplete_reason','')}")

    # --digest: also print plain-text P1+P2 digest to stdout
    if args.digest:
        txt = result["artifacts"].get("text", "")
        print("\n" + "─" * 60)
        print(txt)

    return 0


def _write_error_report(cfg: dict, exc: Exception) -> None:
    """Write a minimal error report so the failure is traceable."""
    try:
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc)
        out = Path(cfg.get("output_dir", "./reports")) / dt.strftime("%Y%m%d")
        out.mkdir(parents=True, exist_ok=True)
        error_file = out / "email-triage-error.txt"
        error_file.write_text(
            f"EmailPrioritizationAgent error — {dt.isoformat()}\n\n{exc}\n\n"
            + traceback.format_exc(),
            encoding="utf-8",
        )
        print(f"  Error report written to: {error_file.resolve()}", file=sys.stderr)
    except Exception:
        pass  # best-effort; don't mask the original error


if __name__ == "__main__":
    sys.exit(main())
