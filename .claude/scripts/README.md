# .claude/scripts — EmailPrioritizationAgent

Python implementation. One module per skill.

## Modules

| Module | Skill |
|--------|-------|
| `email_agent/config.py` | Config load & validation |
| `email_agent/auth.py` | MSAL token acquisition (device-code / silent) |
| `email_agent/ingest.py` | Microsoft Graph email fetch |
| `email_agent/extract.py` | Signal extraction per email |
| `email_agent/score.py` | Weighted urgency scoring |
| `email_agent/rank.py` | P1–P4 tier assignment + SLA-floor rule |
| `email_agent/recommend.py` | Action, reply tone, effort estimate |
| `email_agent/report.py` | HTML + JSON + plain-text report generation |
| `email_agent/writer.py` | Local report writer |
| `email_agent/pipeline.py` | Full pipeline orchestration |
| `prioritize_emails.py` | CLI entry point |

## Quick Start

```sh
# 1. Install dependencies
pip install -r requirements.txt

# 2. First-time authentication (opens browser device-code flow)
python prioritize_emails.py --setup

# 3. Run triage
python prioritize_emails.py                    # last 24 hours
python prioritize_emails.py --since 2d        # last 2 days
python prioritize_emails.py --digest          # morning digest (last 18 h)
python prioritize_emails.py --since 4h --folder Focused

# 4. Run tests
pytest tests/ -v
```

## Output

```
reports/<yyyymmdd>/
    email-triage.html     # color-coded P1–P4 triage table
    email-triage.json     # machine-readable sidecar
    email-triage.txt      # P1+P2 plain-text digest
```
