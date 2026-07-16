## Instruction → Agent Mapping

| Instruction | Agent | Description |
|-------------|-------|-------------|
| `Prioritize emails` | [prioritize-emails](.claude/agents/prioritize-emails.md) | Microsoft 365 connector–native email triage advisor. Reads the configured Outlook inbox via the connector, scores every unread/recent email via a multi-signal model (sender authority, action language, recency, thread depth, importance, attachments), ranks into P1–P4 tiers, and emits a prioritized triage report (HTML + JSON + plain-text). Read-only on the mailbox — no send, no delete, no move. |
| `Prioritize emails --since <duration>` | [prioritize-emails](.claude/agents/prioritize-emails.md) | Same triage, scoped to emails received within the given window (e.g. `--since 2d` = last 2 days, `--since 4h` = last 4 hours). Useful for catching up after a gap. |
| `Prioritize emails --folder <name>` | [prioritize-emails](.claude/agents/prioritize-emails.md) | Same triage, scoped to a specific Outlook folder (e.g. `--folder "Focused"` or `--folder "Inbox"`). Combine with `--since` for fine-grained scoping. |
| `Prioritize emails --digest` | [prioritize-emails](.claude/agents/prioritize-emails.md) | Morning digest mode: scans the last 18 hours, produces a compact P1+P2-only plain-text summary suitable for a notification or Teams message, plus the full HTML/JSON report. Designed for a scheduled daily run at the start of the work day. |
| `Draft replies` | [draft-replies](.claude/agents/draft-replies.md) | Composes AI-drafted Outlook replies for the most recent triage's "Directed at You" items that need a reply (personally/small-team addressed, not mass distribution). Pulls in live Jira/Confluence status when the email references a ticket or page. Creates Outlook drafts — never sends. |
| `Draft replies --for <selector>` | [draft-replies](.claude/agents/draft-replies.md) | Same, but for one specific email named by sender or subject snippet, on demand — works even if it wasn't in the latest triage. |

---

## Execution (connector mode)

Mail is fetched through the **Microsoft 365 connector** — there is no Azure app,
no MSAL, and no Microsoft Graph HTTP call. The connector's tools are only
callable by Claude, so `Prioritize emails` is Claude-driven:

1. Claude calls the connector `outlook_email_search` for the requested folder +
   window, paging until covered.
2. Claude writes the results to a JSON dump (array of email objects).
3. Claude runs the scoring script over that dump. Reports are written to
   `./reports/yyyymmdd/`.

```sh
# after Claude has written the connector dump to emails.json:
python .claude/scripts/prioritize_emails.py --input emails.json               # score the dump
python .claude/scripts/prioritize_emails.py --input emails.json --since 2d    # look-back filter
python .claude/scripts/prioritize_emails.py --input emails.json --digest      # morning digest (P1+P2)
python .claude/scripts/prioritize_emails.py --input emails.json --folder Focused
```

> **Note:** because the connector requires a live Claude session, unattended /
> scheduled headless runs are not supported in connector mode.

### Report layout

```
reports/<yyyymmdd>/
    email-triage.html     # self-contained HTML dashboard (KPIs, Directed at You,
                           # Priority Inbox, Inbox Breakdown) — no build step, no
                           # backend, works fully offline
    email-triage.json     # machine-readable sidecar
    email-triage.txt      # plain-text digest (P1 + P2)
    drafts.json           # written by `Draft replies` — original message id →
                           # {draft_id, draft_weblink, jira_refs, confluence_refs}.
                           # Picked up automatically by the next `Prioritize emails`
                           # run so the dashboard shows "📝 Draft ready" on that row.
```

### Draft & send boundary

`Draft replies` composes and creates Outlook drafts — it never sends. Sending
only ever happens one of two ways:
- **You open the linked draft in Outlook and click Send there** — the
  dashboard's "Draft ready" link goes straight to the draft; a static,
  offline HTML file has no way to authenticate to the mailbox or call a send
  tool itself.
- **You ask Claude to send a specific draft in chat** — Claude re-displays
  that exact draft's recipient/subject/full body and requires a confirmation
  naming that draft before calling send. Never automatic, never batch, never
  on a bare "yes."

### Credentials

None to configure. Authentication is handled entirely by the **Microsoft 365
connector** (authorized once in your claude.ai connector settings) and, for
Jira/Confluence context in `Draft replies`, the **Atlassian connector**
(authorized the same way). No Azure app registration, no `tenant_id`/
`client_id`, no MSAL token cache. See [HELP-CONFIG.md](HELP-CONFIG.md).

Jenkins, AWS, and Snowflake have no connector in this environment — `Draft
replies` will not attempt to reach them. Connect them as MCP servers in an
interactive session first if you want that context pulled in too.

---

## GitHub Copilot

This agent is portable. In GitHub Copilot, invoke:

```
Prioritize emails
```

Copilot reads the canonical agent at [.claude/agents/prioritize-emails.md](.claude/agents/prioritize-emails.md). See [.claude/prompts/invocation-prompts.md](.claude/prompts/invocation-prompts.md) for both Claude Code and Copilot entry points.
