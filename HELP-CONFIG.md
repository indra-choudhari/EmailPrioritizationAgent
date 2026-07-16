# HELP-CONFIG — EmailPrioritizationAgent (connector mode)

This agent reads mail through the **Microsoft 365 connector**. There is **no
Azure app registration, no client/tenant ID, and no MSAL token** to manage.

---

## 1. Authorize the Microsoft 365 connector

Authentication is handled by the connector, authorized once in your **claude.ai
connector settings** (Settings → Connectors → Microsoft 365 → Connect). It signs
you in with your Microsoft 365 account and manages token refresh for you.

To confirm it is connected, ask Claude to run the connector's `get_me` — it
should return your profile (name, mail, job title).

> ⚠️ The agent is **read-only**: it uses only the connector's search/read tools
> (`outlook_email_search`, `read_resource`) and never sends, drafts, forwards,
> deletes, moves, or labels mail.

---

## 2. How a triage runs

The connector's tools are callable only by Claude, so the run is Claude-driven:

1. Claude calls `outlook_email_search` for the folder + window, paging as needed.
2. Claude writes the results to a JSON dump — an array of objects with keys
   `subject, sender, receivedDateTime, importance, hasAttachments, isRead,
   summary, id, webLink`.
3. Claude scores the dump:

```sh
python .claude/scripts/prioritize_emails.py --input emails.json            # score a dump
python .claude/scripts/prioritize_emails.py --input emails.json --since 4h # look-back filter
python .claude/scripts/prioritize_emails.py --input emails.json --digest   # morning digest (P1+P2)
```

Expected terminal output:
```
✓ Triage complete — 3 P1, 7 P2, 12 P3, 31 P4.  Report: reports/20260715/email-triage.html
```

Just say **`Prioritize emails`** (optionally with `--since` / `--folder` /
`--digest`) and Claude performs all three steps.

---

## 3. Configure `config.json`

No credentials. Tune scoring inputs only:

```json
{
  "mailbox": "me",
  "folder": "Inbox",
  "since_hours": 24,
  "local": true,
  "output_dir": "./reports",
  "internal_domains": ["nice.com", "niceincontact.com"],
  "vip_senders": [
    "ceo@yourcompany.com",
    "key.customer@client.com"
  ],
  "manager_emails": [
    "your.manager@yourcompany.com"
  ]
}
```

`vip_senders` and `manager_emails` drive the highest sender-authority scores
(100 / 80) and are the main way to surface P1/P2. Since the connector does not
expose relationship data, all other senders are classified heuristically from
their address (see `internal_domains` and `ingest._classify_sender`).

---

## 4. Config Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `internal_domains` | array | `["nice.com","niceincontact.com"]` | Domains treated as internal for sender classification |
| `mailbox` | string | `"me"` | Mailbox to scan (`"me"` = signed-in user) |
| `folder` | string | `"Inbox"` | Outlook folder name |
| `since_hours` | int | `24` | Default look-back window in hours |
| `local` | bool | `true` | Write reports locally; `false` = OneDrive/SharePoint (future) |
| `output_dir` | string | `"./reports"` | Local report output directory |
| `vip_senders` | array | `[]` | Email addresses always scored as sender authority = 100 |
| `manager_emails` | array | `[]` | Direct manager(s) — scored as authority = 80 |
| `high_priority_keywords` | array | (see file) | Keywords triggering high action-language score |
| `sla_floor_keywords` | array | (see file) | Keywords that floor score to P1 if score ≥ 50 |
| `weights` | object | (see file) | Scoring signal weights — must sum to 1.0 |
| `user_email` | string | — | Your own mailbox address. Drives "Directed at You" classification — must be in an email's `recipients` array for it to count as directed. |
| `directed_recipient_max` | int | `15` | Above this many recipients, an email is treated as a broadcast/distribution list, never "directed," regardless of whether you're named. |
| `atlassian_cloud_id` | string or `null` | `null` | Cached Atlassian `cloudId`, auto-populated by `Draft replies` on its first Jira/Confluence lookup (via `getAccessibleAtlassianResources`) so later runs skip the resolve step. |

The connector dump (step 2 in [prioritize-emails.md](.claude/agents/prioritize-emails.md))
also now includes a `recipients` array per email — already returned by
`outlook_email_search`, just previously undocumented. It costs nothing extra to
fetch and is what makes `user_email`/`directed_recipient_max` classification
possible.
