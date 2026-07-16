# VIBE-CODING — EmailPrioritizationAgent

> **Source PLANNER:** [./PLANNER.md](./PLANNER.md)  
> **Goal recap:** Build a Microsoft Graph–native, **read-only / advisory-only** agent that reads an Outlook inbox, scores every email via a multi-signal model, ranks into P1–P4 tiers, and emits a triage report (HTML + JSON + plain-text). **Never sends, moves, or deletes any email.**

---

## Prerequisites & Setup

- **Language/stack:** Python 3.12 + `msal` + `requests` (Graph API calls). No external ML model required — pure weighted scoring.
- **Microsoft 365 access:** Azure AD app registration with `Mail.Read` + `People.Read` delegated scopes. **No** `Mail.ReadWrite` or `Mail.Send`.
- **Tools:** `python>=3.12`, `pip`, `keyring` (OS credential store), optional `pytest`.
- **Source of truth for fields/sample output:** [0-prd.md](./0-prd.md) §8 (Sample Output) and §6 (Scoring Model). Mirror their shape.

---

## Session Memory & Checkpoints

- After each step, **checkpoint** the module's public function signature(s) into session memory so later steps call them without re-reading files.
- The **canonical data contract** (checkpointed at Step 3): `raw_messages → validated_messages → scored_emails → ranked_tiers → recommendations → report_artifacts`.
- Keep full email bodies out of the running narrative; summarize to signal scalars (sender_score, keyword_score, recency_score) to stay token-frugal.
- Pause for user evaluation after every step before advancing.

---

## Build Steps

### Step 1 — Project scaffold & config schema

**Action:** Create the project: `email_agent/` package with empty modules (`config.py`, `auth.py`, `ingest.py`, `extract.py`, `score.py`, `rank.py`, `recommend.py`, `report.py`, `writer.py`, `pipeline.py`), a `config.json` with the schema below, `requirements.txt` (`msal requests keyring`), and `tests/`.

**`config.json` schema:**
```json
{
  "tenant_id": "<azure-tenant-id>",
  "client_id": "<app-client-id>",
  "mailbox": "me",
  "folder": "Inbox",
  "since_hours": 24,
  "local": true,
  "output_dir": "./reports",
  "vip_senders": ["ceo@company.com", "cto@company.com"],
  "high_priority_keywords": ["urgent", "action required", "P0", "incident", "deadline", "by EOD", "ASAP"],
  "weights": {
    "sender_authority": 0.30,
    "action_language":  0.25,
    "recency":          0.20,
    "thread_depth":     0.10,
    "importance_flag":  0.10,
    "has_attachment":   0.05
  }
}
```

**Expected output:** Importable `email_agent` package + valid `config.json`.  
**Verify:** `python -c "import email_agent"` succeeds; `config.json` loads and validates.  
**Traces to:** Constraints (M365-only, local mode), Context C1 (config).

---

### Step 2 — Auth & token acquisition (MSAL)

**Action:** In `auth.py`, implement two flows:
- **Interactive (device-code):** for first-time / on-demand runs — prompts user to visit a URL and enter a code; caches token in OS keychain via `keyring`.
- **Silent (cached token):** for subsequent runs — load from keychain, refresh if expired.
- Scopes: `["Mail.Read", "People.Read", "offline_access"]` **only**. Refuse to acquire any write/send scope.
- `--setup` flag triggers the device-code flow explicitly.

**Expected output:** `get_token() -> str` (bearer token); `setup_credentials()` for first-time flow.  
**Verify:** Token obtained; decoded JWT contains only `Mail.Read` + `People.Read` scopes; no `Mail.Send` or `Mail.ReadWrite` present.  
**Traces to:** Constraints (read-only scopes), Guardrails (no mutations), Security.

---

### Step 3 — Email ingestion (Graph API)

**Action:** In `ingest.py`, fetch emails from Graph `/v1.0/me/messages` with:
- `$select=id,subject,from,receivedDateTime,importance,hasAttachments,conversationId,bodyPreview,isRead`
- `$filter` by `receivedDateTime` (respecting `--since` window) and folder
- `$orderby=receivedDateTime desc`
- `$top=50` with auto-pagination up to 500 emails (follow `@odata.nextLink`)
- Body preview **capped at 200 characters** (Graph's `bodyPreview` field is already ≤255 chars; slice to 200)
- Also fetch sender relationship via `/v1.0/me/people?$search="<sender_email>"` for each unique sender (batched)

**Canonical data contract** (checkpoint this):
```python
RawEmail = {
  "id": str,
  "subject": str,
  "from_name": str,
  "from_email": str,
  "received_at": datetime,   # UTC
  "importance": str,          # "normal" | "high" | "low"
  "has_attachments": bool,
  "conversation_id": str,
  "body_preview": str,        # ≤200 chars
  "is_read": bool,
  "sender_relationship": str  # "manager"|"direct_report"|"frequent"|"external"|"unknown"
}
```

**Expected output:** `fetch_emails(token, config, since_hours, folder) -> list[RawEmail]`  
**Verify:** Returns populated list; `body_preview` never exceeds 200 chars; no Graph write endpoints called.  
**Traces to:** Context C1 (data sources), Constraints (read-only, body preview only), Performance (≤60 s / 500 emails).

---

### Step 4 — Signal extraction

**Action:** In `extract.py`, derive scoring signals from each `RawEmail`:
- `sender_authority_score`: 100 if VIP, 80 if manager, 70 if direct_report, 60 if frequent, 30 if external, 10 if unknown
- `action_language_score`: keyword match count in (subject + body_preview) → normalized 0–100
- `recency_score`: received < 2 h → 100; < 8 h → 70; < 24 h → 40; older → 10
- `thread_depth_score`: count of emails in `conversation_id` already in the fetched batch → normalized 0–100 (more replies = higher score, signals active thread)
- `importance_score`: `"high"` → 100; `"normal"` → 30; `"low"` → 0
- `attachment_score`: `True` → 100; `False` → 0

**Expected output:** `extract_signals(email: RawEmail, config) -> SignalVector` (a dict of the 6 scores above).  
**Verify:** VIP sender + "urgent" subject → high sender + high action scores; newsletter with no keywords → near-zero action score.  
**Traces to:** Context C3 (scoring signals), Guardrails (user-curated VIP list, visible weights).

---

### Step 5 — Multi-signal scoring

**Action:** In `score.py`, apply the weighted formula:

```
urgency_score = sum(weight_i * signal_i for i in signals)   # 0–100
```

Weights from `config["weights"]`. Produce:
- `urgency_score` (0–100, rounded to 1 decimal)
- `top_3_signals`: the 3 signals contributing most to the score (name + weighted contribution)
- `confidence`: `"high"` if ≥ 3 signals have non-zero data; `"medium"` if 1–2; `"low"` if sender relationship unknown AND no keywords matched

**Expected output:** `score_email(signals: SignalVector, config) -> ScoredEmail` (adds `urgency_score`, `top_3_signals`, `confidence` to the dict).  
**Verify:** VIP + urgent + recent → score 80+; newsletter → score < 30; top-3 signals correctly identify the dominant drivers.  
**Traces to:** Context C3, Guardrails GR1 (signal breakdown), GR3 (configurable weights).

---

### Step 6 — Priority ranking & tier assignment

**Action:** In `rank.py`:
- Sort emails by `urgency_score` descending.
- Assign tier: P1 (80–100), P2 (55–79), P3 (30–54), P4 (0–29).
- **SLA floor rule:** if subject/body contains a same-day deadline keyword (`"by EOD"`, `"by end of day"`, `"by 5pm"`, `"today"`) AND score ≥ 50, floor the tier to P1.
- Return tier-grouped structure: `{"P1": [...], "P2": [...], "P3": [...], "P4": [...]}`.

**Expected output:** `rank_emails(scored_emails: list[ScoredEmail], config) -> TieredResult`  
**Verify:** SLA-floor rule promotes a 60-score "by EOD" email to P1; a 60-score general email stays P2.  
**Traces to:** G1, G3, Constraints (no auto-action), Guardrails GR2.

---

### Step 7 — Action recommendation

**Action:** In `recommend.py`, map each email's tier + signals to:
- `suggested_action`: `"Reply now"` / `"Reply today"` / `"Review when free"` / `"Archive / no action"`
- `reply_tone`: `"formal"` (external / exec) / `"concise"` (peer / direct report) / `"empathetic"` (if subject contains emotional keywords like `"concern"`, `"issue"`, `"frustrated"`)
- `effort_estimate`: `"quick"` (P4/P3, no attachment) / `"medium"` (P2, short thread) / `"detailed"` (P1, attachment or long thread)

**Expected output:** `recommend(email: ScoredEmail) -> RecommendedEmail` (adds the 3 fields above).  
**Verify:** P1 external VIP → "Reply now" + "formal" + "detailed"; P4 newsletter → "Archive / no action" + no tone/effort.  
**Traces to:** Goal G4, Output Format (per-email detail), Guardrails GR6 (advisory framing).

---

### Step 8 — Report generation

**Action:** In `report.py`, render three artifacts:

**HTML (canonical):**
- Header: "Email Triage — {date} {time}" + executive summary line ("3 P1 emails require response in the next hour. 7 P2 emails by end of day.")
- Per-tier section: color-coded table (P1 red, P2 orange, P3 yellow, P4 grey) with columns: Priority | Score | From | Subject | Received | Reason (top-3 signals) | Action | Tone | Effort
- Footer: scan metadata (folder, window, total count, run time, incomplete-scan warning if applicable)
- **"Inbox clear"** variant: single-panel "No actionable emails found in the scan window."
- **"Incomplete scan"** variant: banner warning + partial results table

**JSON sidecar:** Array of `RecommendedEmail` objects — all fields, no full body, ISO timestamps.

**Plain-text digest:** 
```
📬 Email Triage — {date}
P1 – Respond Now ({n})
  • [Sender] "Subject" — Score {n}  [{action}]
...
P2 – Respond Today ({n})
  • ...
---
{n} P3/P4 emails de-prioritized. Full report: reports/{yyyymmdd}/email-triage.html
```

**Expected output:** `build_report(tiered: TieredResult, meta: dict) -> {html: str, json: str, text: str}`  
**Verify:** Full path renders all tiers + signals; "inbox clear" variant renders correctly; JSON is valid and parseable.  
**Traces to:** Output Format §7, Guardrails GR6, 0-prd.md §8 (sample output shape).

---

### Step 9 — Local report writer

**Action:** In `writer.py`:
- Create `reports/yyyymmdd/` directory (today's UTC date).
- Write `email-triage.html`, `email-triage.json`, `email-triage.txt`.
- **Never overwrite** unless `--overwrite` flag is passed; if file exists, append a timestamp suffix instead.
- Log the absolute path of each written file.

**Expected output:** `write_reports(artifacts: dict, output_dir: str, overwrite: bool) -> list[str]` (paths written).  
**Verify:** Files created at correct path; re-run without `--overwrite` creates a timestamped copy, not an overwrite.  
**Traces to:** Constraints C3 (no full-body storage), Output Format §7.1.

---

### Step 10 — Pipeline CLI (`prioritize_emails.py`)

**Action:** In `pipeline.py` + `prioritize_emails.py` CLI entry point:
- Wire all steps: `auth → ingest → extract → score → rank → recommend → report → write`
- CLI flags: `--since <duration>` (e.g. `2d`, `4h`), `--folder <name>`, `--digest`, `--overwrite`, `--setup`, `--config <file>`
- `--digest` mode: scope to last 18 h, print plain-text digest to stdout, still write full HTML/JSON.
- `--setup` flag: run `setup_credentials()` only, then exit.
- On any unhandled exception: write a minimal error report to `reports/yyyymmdd/email-triage-error.txt` and exit non-zero.
- Print a one-line summary to stdout on success: `"✓ Triage complete — 3 P1, 7 P2, 12 P3, 31 P4. Report: reports/20260714/email-triage.html"`

**Expected output:** `python prioritize_emails.py` runs end-to-end, prints summary, and writes all 3 artifacts.  
**Verify:** Full pipeline runs against real (or mocked) Graph API; `--digest` prints P1+P2 to stdout; `--since 4h` scopes correctly; no Graph write endpoints are called at any point.  
**Traces to:** All goals, all constraints, all guardrails.

---

### Step 11 — Tests

**Action:** In `tests/`, write unit tests covering:
- `extract_signals`: VIP sender → high authority score; unknown sender → low; "urgent" keyword → high action score
- `score_email`: correct weighted sum; top-3 signals identified correctly
- `rank_emails`: SLA-floor promotion; correct tier boundaries
- `recommend`: P1 external → "Reply now" + "formal"; P4 → "Archive"
- `build_report`: "inbox clear" variant; "incomplete scan" banner; JSON validity
- Integration smoke test (mocked Graph responses): full pipeline produces 3 artifacts

**Expected output:** `pytest tests/` passes; ≥80 % line coverage on scoring + ranking modules.  
**Traces to:** All skills, KPIs.

---

## Completion Checklist

- [ ] `email_agent/` package imports cleanly
- [ ] `config.json` validates (schema check)
- [ ] MSAL device-code flow works; token cached in keychain
- [ ] Graph calls use only `Mail.Read` + `People.Read` scopes
- [ ] `body_preview` capped at 200 chars — verified in `ingest.py`
- [ ] No Graph write endpoints called anywhere (`grep -r "POST\|PATCH\|DELETE" email_agent/` returns nothing relevant)
- [ ] Scoring weights sum to 1.0 (validated in `config.py`)
- [ ] SLA-floor rule unit tested
- [ ] HTML report renders all tiers + signal breakdown
- [ ] "Inbox clear" and "incomplete scan" variants tested
- [ ] Report written to `reports/yyyymmdd/` — no overwrite without flag
- [ ] `pytest tests/` passes
- [ ] `python prioritize_emails.py --digest` prints P1+P2 digest to stdout
