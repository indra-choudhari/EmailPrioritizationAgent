# EmailPrioritizationAgent

> Microsoft 365 connector–native email triage assistant — reads your Outlook inbox, scores each email by urgency and business impact, ranks it into P1–P4 tiers, and produces a prioritized triage report and dashboard. **Read-only: it never sends, replies, deletes, moves, or read-flags mail.**

## What it does

For the signed-in Microsoft 365 mailbox, the agent reads unread/recent email, applies a multi-signal urgency model (sender authority, action language, recency, thread depth, importance flag, attachments), and produces a **prioritized response plan** — a ranked list of emails, each with a recommended action (reply now / reply today / review / archive), a suggested reply tone, and an effort estimate. It is **advisory-only**; its sole side effect is writing report files locally.

## How it works (connector mode)

Mail is fetched through the **Microsoft 365 connector** — there is **no Azure app registration, no MSAL, no `tenant_id`/`client_id`, and no Microsoft Graph HTTP call**. The connector's tools are callable only by Claude, so a run is Claude-driven in three steps:

1. Claude calls the connector `outlook_email_search` for the requested folder + window (paging as needed).
2. Claude writes the results to a JSON dump.
3. Claude runs the scoring script over that dump; reports are written to `reports/yyyymmdd/`.

Just say **`Prioritize emails`** and Claude performs all three. Authentication is handled once in your claude.ai connector settings — see [HELP-CONFIG.md](HELP-CONFIG.md).

> **Note:** because the connector needs a live Claude session, unattended/scheduled headless runs are not supported in connector mode.

## Invocation

```
Prioritize emails                     # unread / recent (default: last 24 h)
Prioritize emails --since 2d          # last 2 days
Prioritize emails --since 7d          # last week
Prioritize emails --folder Inbox      # a specific folder
Prioritize emails --digest            # morning digest (P1 + P2 to stdout)
```

## Prioritization model

Each email gets a 0–100 **urgency score** = weighted sum of six signals (weights in [config.json](config.json), must sum to 1.0):

| Signal | Weight | What it measures |
|---|--:|---|
| Sender authority | 0.30 | VIP / manager / frequent colleague / external / unknown |
| Action language | 0.25 | high-priority keywords in subject + preview (3+ hits = full score) |
| Recency | 0.20 | ≤2 h = 100, ≤8 h = 70, ≤24 h = 40, older = 10 |
| Thread depth | 0.10 | number of messages in the conversation |
| Importance flag | 0.10 | Outlook High / Normal / Low |
| Attachment | 0.05 | has attachments |

Score → tier: **P1 ≥ 80 · P2 ≥ 55 · P3 ≥ 30 · P4 < 30**.

### Override rules (floors)

Three rules can raise an email's tier above its raw score:

- **Keyword floor** (`priority_keyword_floors`) — *score-independent.* "critical" anywhere in subject/body → **P1**; "urgent" → **P2**.
- **Onboarding floor** (`onboarding_*`) — Product-Type / Telemetry onboarding requests (subject contains "onboarding", or body contains `prod_type_id` / "product type onboarding" / "onboarding request") → floored to **P2**, since they're team work even when sent by automated systems.
- **SLA floor** (`sla_floor_keywords`) — a same-day-deadline keyword ("by EOD", "today", …) **and** score ≥ 50 → **P1**.

Floors only ever raise priority, never lower it.

### Sender classification

The connector doesn't expose relationship data, so sender authority is inferred: addresses in `vip_senders` → VIP (100) or `manager_emails` → manager (80); automated / no-reply / bulk addresses → unknown (10); named people on `internal_domains` → frequent (55); other domains → external (30). **Populating `vip_senders` / `manager_emails` is the main lever for surfacing genuine P1/P2.**

## Output

The scoring pipeline writes to `reports/yyyymmdd/`:

| File | What |
|---|---|
| `email-triage.html` | color-coded report (canonical) |
| `email-triage.json` | machine-readable sidecar |
| `email-triage.txt` | plain-text P1 + P2 digest |

Each entry carries: priority tier, urgency score, top-3 contributing signals, suggested action, reply tone, and effort estimate.

### Interactive dashboard

Claude can also render an interactive, theme-aware dashboard (`reports/yyyymmdd/email-triage-dashboard.html`) from the triage JSON, with:

- **KPI tiles** — needs-response, to-review, unread, inbox volume, follow-ups
- **Priority distribution** bar (P1–P4)
- **Follow-up reminders** — mail *you* sent that's still awaiting a reply
- **Action needed** — P1 & P2 cards with sender, subject and one-line summary
- **To review (P3)** — scannable list
- **By category** — Team thread / Deployment / Prod Alert / CI-Build / Report / Meeting / Newsletter / Notification / …
- **Onboarding Governance** — integration & onboarding process/governance threads
- **Organization events** — company-wide programs, summits, sessions
- Collapsed **P4** bucket

## Configuration

No credentials. Tune scoring inputs in [config.json](config.json):

| Key | Purpose |
|---|---|
| `internal_domains` | domains treated as internal for sender classification |
| `vip_senders` / `manager_emails` | elevate specific senders to authority 100 / 80 |
| `high_priority_keywords` | action-language keywords |
| `priority_keyword_floors` | keyword→tier hard floors (critical→P1, urgent→P2) |
| `onboarding_floor_tier` / `onboarding_subject_keywords` / `onboarding_text_keywords` | onboarding detection + floor |
| `sla_floor_keywords` | same-day deadline keywords for the SLA floor |
| `weights` | signal weights (must sum to 1.0) |
| `folder` / `since_hours` / `output_dir` | scan window & output |

## Run locally

```sh
# No dependencies — standard library only. (requirements.txt is intentionally empty.)
# After Claude has written the connector results to emails.json:
python .claude/scripts/prioritize_emails.py --input emails.json
python .claude/scripts/prioritize_emails.py --input emails.json --since 2d
python .claude/scripts/prioritize_emails.py --input emails.json --digest
```

Run the tests:

```sh
python -m pytest .claude/scripts/tests/   # or run the files directly if pytest is unavailable
```

## Pipeline

`Prioritize emails` runs an ordered pipeline (no auth step — the connector handles that):

1. **Ingest** — load + normalize the connector JSON dump; derive thread depth and sender relationship ([ingest.py](.claude/scripts/email_agent/ingest.py))
2. **Extract** — compute the six scoring signals ([extract.py](.claude/scripts/email_agent/extract.py))
3. **Score** — weighted urgency score + top-3 signal breakdown ([score.py](.claude/scripts/email_agent/score.py))
4. **Rank** — P1–P4 tiers + keyword / onboarding / SLA floors ([rank.py](.claude/scripts/email_agent/rank.py))
5. **Recommend** — action + reply tone + effort estimate ([recommend.py](.claude/scripts/email_agent/recommend.py))
6. **Report** — HTML + JSON + plain-text ([report.py](.claude/scripts/email_agent/report.py))
7. **Write** — save to `reports/yyyymmdd/` ([writer.py](.claude/scripts/email_agent/writer.py))

## Structure

```
EmailPrioritizationAgent/
├── README.md            # This overview
├── CLAUDE.md            # Instruction → agent mapping + Copilot entry point
├── HELP-CONFIG.md       # Connector setup + config reference
├── config.json          # Scoring weights, keyword floors, VIP/manager lists
├── PLANNER.md / 0-prd.md / VIBE-CODING.md   # spec & build notes
├── reports/<yyyymmdd>/  # generated reports + dashboard
└── .claude/
    ├── agents/          # prioritize-emails.md (canonical agent definition)
    ├── templates/       # report template
    └── scripts/
        ├── prioritize_emails.py     # CLI entry point (--input dump.json)
        ├── requirements.txt         # empty — stdlib only
        ├── email_agent/             # config, ingest, extract, score, rank,
        │                            #   recommend, report, writer, pipeline
        └── tests/                   # scoring + connector-ingest unit tests
```

## Guarantees & limitations

- **Read-only.** The agent uses only the connector's search/read tools; it never sends, drafts, forwards, deletes, moves, labels, or read-flags mail.
- **Advisory-only.** Its only side effect is writing report files.
- **Connector mode is not built for bulk export.** For very large windows (e.g. a full week of a high-volume inbox), the connector returns big result pages inline rather than to disk, so full-volume analytics may cover a representative subset rather than every message. The tiers and human/actionable threads remain well-covered; automated CI/deploy/report noise is what gets under-sampled.
