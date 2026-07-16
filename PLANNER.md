# EmailPrioritizationAgent — Planner

_Elicited spec: goal → constraints → guardrails → output._

---

## Instruction
`Prioritize emails` — reads the configured Microsoft 365 mailbox, scores every email, and produces a prioritized triage report. Scoped to one mailbox per run; folder and time-window configurable.

## Raw Goal
A Microsoft Graph–native email triage agent that reads the inbox, applies a multi-signal urgency-scoring model (sender authority, action language, recency, thread depth, importance flag, attachments), ranks emails into P1–P4 tiers, and produces a prioritized response plan — **without sending, moving, or deleting anything**.

---

## Agent Definition

### Role
**Email Triage Advisor** — a Microsoft 365–native productivity assistant that reads an Outlook inbox, scores each email by urgency and business impact, ranks them into actionable priority tiers, and delivers a structured response queue. It is **read-only on the mailbox** and its output is **advisory-only**; the human decides what to reply, send, or ignore.

### Goal
**G1 — Primary output:** A per-run **email triage report** that bundles: (1) a **priority-ranked email list** (P1 Respond Now → P4 Archive), (2) a **per-email urgency score** (0–100) with the top signals that drove it, (3) a **suggested action** (reply now / reply today / review / archive) with recommended reply tone (formal / concise / empathetic) and effort estimate (quick / medium / detailed).

**G2 — Trigger modes:** Runs **on-demand** (`Prioritize emails`) and optionally on a **daily morning schedule** (`--digest`). Supports a `--since <duration>` window (e.g. `--since 2d`) and `--folder <name>` to scope to a specific Outlook folder.

**G3 — Success metrics:** (1) **P1 recall ≥ 90 %** — real urgent emails ranked P1; (2) **P4 precision ≥ 85 %** — non-actionable emails correctly suppressed; (3) **false-positive P1 rate ≤ 5 %**; (4) **time-to-first-response on P1 reduced ≥ 30 %**; (5) run completes in **≤ 60 s for 500 emails**.

### Context
**C1 — Data sources:** Microsoft Graph API: `/me/messages` (subject, sender, body preview ≤200 chars, received time, importance, conversationId, hasAttachments), `/me/people` (sender relationship: manager / direct report / frequent contact / external). Locally configured: VIP sender list, high-priority keyword list, scoring weights.

**C2 — Consumers:** (1) **Individual contributor** — morning "what do I respond to first?" queue; (2) **Manager/Director** — escalation radar (direct-report + exec visibility); (3) **On-call engineer** — incident-related email surfaced above everything else.

**C3 — Analytical method:** Multi-signal weighted scoring — sender authority (30 %), action-required language in subject + body preview (25 %), recency (20 %), thread depth + unread count (10 %), importance flag (10 %), attachments (5 %). Weights are configurable in `config.json`. Score → tier mapping: 80–100 = P1, 55–79 = P2, 30–54 = P3, 0–29 = P4.

### Constraints
**Technical/environmental:**
- **Microsoft 365 / Outlook only** in v1 — Microsoft Graph API (`https://graph.microsoft.com/v1.0`); no Gmail, no IMAP.
- **Read-only on the mailbox** — permitted Graph scopes: `Mail.Read`, `People.Read`. **No** `Mail.Send`, `Mail.ReadWrite`, or any destructive scope.
- **Body preview only** — only the first 200 characters of the body are fetched for keyword analysis; the full body is never stored.
- Performance: ≤ 60 s for 500 emails; Graph calls batched via `$batch` endpoint.

**Scope/behavioral limits:**
- **No auto-reply, no auto-send** — the agent never calls any send/compose Graph endpoint.
- **No auto-move or auto-delete** — mailbox state is never modified.
- **No full-body LLM analysis** unless `--draft` flag is explicitly passed (future feature; not in scope for v1).

**Security/credentials:**
- `client_secret` / OAuth tokens stored in **OS keychain (`keyring`)** or environment variables; **never** written to `config.json` plaintext.
- Credentials are never logged or included in report output.

### Guardrails
**Accuracy:**
- Every score includes a **top-3 signal breakdown** (e.g. "VIP sender +28, action keyword +22, recency +18") so the user can audit the ranking.
- Scoring weights are **user-visible and configurable** — no hidden model weights.
- **Sender tier is user-curated** — VIP list comes exclusively from `config.json`; the agent never auto-promotes a sender.

**Safety:**
- **No mailbox mutations** — enforced by requesting only `Mail.Read` + `People.Read` OAuth scopes at token acquisition time.
- **Fail-safe on API errors** — partial results are labeled "incomplete scan (N emails skipped)"; the agent never silently omits emails.
- **Privacy** — body preview capped at 200 chars; full body never written to disk, never logged.

**Transparency:**
- Every triage report explicitly states the scan window, folder, and total email count.
- Output is always framed as a recommendation; the agent never implies it sent or acted on anything.
- "No emails found" produces an explicit empty-result report rather than silence.

### Output Format
**Artifact format:**
1. **HTML report** — layered, color-coded triage table (P1 red → P4 grey) + per-email detail panel (score breakdown, suggested tone, effort), written to `reports/yyyymmdd/email-triage.html`.
2. **JSON sidecar** — machine-readable array, one object per email, all scored fields, written to `reports/yyyymmdd/email-triage.json`.
3. **Plain-text digest** — P1 + P2 bullet list suitable for terminal or notification, written to `reports/yyyymmdd/email-triage.txt`.

**Report fields per email:** message ID, sender name/email, sender tier, subject, received timestamp, urgency score, top-3 scoring signals, priority tier (P1–P4), suggested action, suggested reply tone, estimated reply effort.

**Tone & style:** Concise, factual, productivity-grade. Lead with a one-line executive summary ("3 P1 emails require response in the next hour"). Tables are scannable; color/badges convey tier at a glance. Never alarmist.

**Edge-case handling:**
- Zero unread emails → produce an explicit "Inbox clear — no action required" report.
- Graph API error → produce a partial report labeled "incomplete scan" with the error reason and the emails that were successfully scored.
- New contact not in VIP list → scored purely on other signals; never auto-elevated.

---

## Skills Required

1. **Auth & Token Acquisition** — MSAL device-code flow (interactive) or client-credentials flow (scheduled); scopes `Mail.Read People.Read`; token cached in OS keychain.
2. **Email Ingestion** — Graph `/me/messages` with `$select`, `$filter`, `$orderby`, `$top`; batched for performance; body preview ≤ 200 chars.
3. **Signal Extraction** — parse sender, subject, body preview; look up sender relationship via `/me/people`; detect action-required keywords; compute recency bucket; count thread depth.
4. **Multi-Signal Scoring** — apply weighted scoring model; produce 0–100 score + top-3 signal breakdown per email.
5. **Priority Ranking** — sort by score desc; assign P1–P4 tier; apply SLA-awareness (e.g. same-day deadline keywords always P1 floor).
6. **Action Recommendation** — map tier + signals to suggested action, reply tone, and effort estimate.
7. **Report Generation** — render HTML (canonical) + JSON + plain-text; "inbox clear" and "incomplete scan" variants.
8. **Local Report Writing** — write artifacts to `reports/yyyymmdd/`; never overwrite existing reports without `--overwrite` flag.
