# EmailPrioritizationAgent — PRD

> **Version:** 0.1 — July 14 2026  
> **Owner:** You  
> **Status:** Draft

---

## 1. Problem Statement

A busy professional receives 50–200 emails per day across threads of varying urgency. Without structured triage, high-priority messages get buried under newsletters, FYIs, and low-stakes CC chains, causing missed SLAs, delayed decisions, and cognitive overload.

An AI-assisted triage agent that **reads the inbox, scores every email by true urgency, and surfaces a prioritized response queue** removes this bottleneck while keeping the human in full control.

---

## 2. Goals

| # | Goal |
|---|------|
| G1 | Surface the **top-priority emails requiring action** at the start of each work session |
| G2 | Reduce time-to-first-response on P1 emails by ≥ 30 % |
| G3 | Eliminate false-urgent noise (newsletters, automated alerts, CC-only threads) by ≥ 50 % |
| G4 | Provide a **suggested reply tone + effort estimate** so drafting is faster |
| G5 | Be **100 % advisory** — never send, move, or delete any email without explicit human action |

---

## 3. Non-Goals

- Auto-sending replies (human always presses Send)
- Training / fine-tuning a model on email content
- Replacing a full email client or CRM
- Accessing non-Microsoft 365 mailboxes in v1 (Gmail support is a future extension)

---

## 4. Personas

| Persona | Need |
|---------|------|
| **Individual contributor** | Morning digest: "what do I respond to first?" |
| **Manager / Director** | Escalation radar: flag emails from direct reports / execs needing fast turnaround |
| **On-call engineer** | Alert triage: surface incident / page-related emails above everything else |

---

## 5. Data Sources

| Source | Signal |
|--------|--------|
| Microsoft Graph `/me/messages` | Subject, sender, body preview, received time, importance flag, conversation thread, attachments |
| Microsoft Graph `/me/people` | Sender's relationship to me (manager, direct report, frequent contact, external) |
| Configurable keyword lists | High-priority keywords (`urgent`, `action required`, `P0`, `incident`, `deadline`) |
| Configurable sender-tier list | VIP senders (CEO, CTO, key customers) always escalate to P1 |
| Email metadata | Thread depth (reply-chain length), unread count in thread, has-attachment flag |

---

## 6. Scoring Model

### 6.1 Signals & Weights (configurable in `config.json`)

| Signal | Default Weight |
|--------|---------------|
| Sender authority (VIP / manager / external key contact) | 30 % |
| Action-required language in subject + body preview | 25 % |
| Recency (received in last 2 h vs 24 h vs older) | 20 % |
| Thread depth & unread thread count | 10 % |
| Importance flag set by sender | 10 % |
| Has attachment (contract / doc review implied) | 5 % |

### 6.2 Priority Tiers

| Tier | Score Range | Action |
|------|------------|--------|
| **P1 – Respond Now** | 80–100 | Reply within 1 h |
| **P2 – Respond Today** | 55–79 | Reply within business day |
| **P3 – Review** | 30–54 | Read; no immediate reply needed |
| **P4 – Archive / FYI** | 0–29 | No action required |

---

## 7. Output Format

### 7.1 HTML Report (canonical)
- Executive summary: counts per tier, most urgent sender/subject
- Sortable table: Priority | Score | From | Subject | Received | Reason | Suggested Action
- Color-coded rows: red (P1), orange (P2), yellow (P3), grey (P4)
- Per-email detail panel: full reason breakdown, suggested reply tone, effort estimate

### 7.2 JSON Sidecar
Machine-readable array: one object per email with all scored fields.

### 7.3 Plain-Text Digest
Short bullet list of P1 + P2 emails, suitable for a notification body or terminal output.

---

## 8. Sample Output

```
📬 Email Triage — July 14 2026, 08:00

P1 – Respond Now (3 emails)
  • [Sarah Chen / VP Eng] "Production incident — auth service down" — Score 97  [Respond Now]
  • [Customer: Acme Corp] "Contract renewal — decision needed today" — Score 88  [Respond Now]
  • [Alice (manager)] "Need your input on Q3 budget by EOD" — Score 82  [Respond Now]

P2 – Respond Today (7 emails)
  • [Bob / direct report] "Code review request — PR #421" — Score 72  [Reply: concise]
  • ...

P3 – Review (12 emails)
  • [Engineering Digest] "Weekly metrics summary" — Score 44  [Read when free]
  • ...

P4 – Archive / FYI (31 emails)
  • [Newsletters, CC-only, automated alerts] — Score < 30  [No action]
```

---

## 9. Constraints

| # | Constraint |
|---|-----------|
| C1 | **Read-only on the mailbox** — no send, delete, move, or mark-read actions |
| C2 | **Microsoft 365 / Outlook only** in v1 (Graph API) |
| C3 | **No email body storage** — body preview only (first 200 chars) for scoring; full body never written to disk |
| C4 | **No LLM-generated replies** without explicit `--draft` flag (future feature) |
| C5 | Analysis must complete within 60 seconds for up to 500 emails |
| C6 | Credentials stored in OS keychain or env vars — never in `config.json` plaintext |

---

## 10. Guardrails

| # | Guardrail |
|---|----------|
| GR1 | Every score carries a **confidence indicator** and the top 3 signals that drove it |
| GR2 | **Sender-tier list is user-curated** — the agent never auto-promotes a sender to VIP without explicit config |
| GR3 | Scoring weights are **visible and configurable** — no black-box decisions |
| GR4 | **Fail-safe on API errors** — partial results labeled "incomplete scan"; never silently drop emails |
| GR5 | **Privacy** — body preview truncated at 200 chars; full body never logged or stored |
| GR6 | Output is always framed as a recommendation; the agent never implies it acted on any email |

---

## 11. KPIs

| Metric | Target |
|--------|--------|
| P1 recall (real urgent emails ranked P1) | ≥ 90 % |
| P4 precision (non-actionable correctly suppressed) | ≥ 85 % |
| Time-to-first-response on P1 | −30 % vs baseline |
| False-positive P1 rate | ≤ 5 % |
| Run time for 500 emails | ≤ 60 s |

---

## 12. Future Extensions

- Gmail / IMAP support
- `--draft` flag: LLM-assisted reply draft attached to each P1 email
- Calendar integration: deprioritize emails about meetings already accepted
- Slack / Teams notification for P1 emails
- Weekly trend report: "your inbox load this week vs last week"
