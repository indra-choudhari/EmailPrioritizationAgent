"""
email_agent/report.py — Generate HTML, JSON, and plain-text triage reports.

The HTML artifact is a self-contained, offline-capable dashboard (no build
step, no backend) — all data for the run is embedded as a JSON blob and
rendered client-side. Colors follow the project's validated status/categorical
palette (P1-P4 = status colors; inbox-breakdown categories = categorical
slots 1-6, stepped separately for light/dark).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

_TIER_LABEL = {
    "P1": "P1 – Respond Now",
    "P2": "P2 – Respond Today",
    "P3": "P3 – Review",
    "P4": "P4 – Archive / FYI",
}


def build_report(tiered: dict[str, list[dict]], meta: dict[str, Any],
                  drafts: dict[str, dict] | None = None) -> dict[str, str]:
    """Build HTML + JSON + plain-text artifacts.

    Args:
        tiered: tier-grouped emails from rank.rank_emails() + recommend.recommend()
        meta: scan metadata: folder, since_hours, total_count, run_time_s,
              incomplete (bool), incomplete_reason (str), scan_dt (datetime),
              user_display_name (optional, from pipeline.run())
        drafts: optional {original_message_id: {"draft_weblink": str, ...}} —
                if a directed/reply-needed email has an entry here, the
                dashboard shows "Draft ready" and links to the draft instead
                of the original message. Written by the `Draft replies` agent
                to reports/<yyyymmdd>/drafts.json; read by pipeline.run().

    Returns:
        {"html": str, "json": str, "text": str}
    """
    all_emails = [e for tier in tiered.values() for e in tier]
    total = meta.get("total_count", len(all_emails))

    if total == 0:
        return _inbox_clear_report(meta)

    return {
        "html": _build_html(tiered, meta, drafts or {}),
        "json": _build_json(tiered, meta),
        "text": _build_text(tiered, meta),
    }


# ── HTML dashboard ───────────────────────────────────────────────────────────

def _build_html(tiered: dict, meta: dict, drafts: dict[str, dict]) -> str:
    payload = _dashboard_payload(tiered, meta, drafts)
    data_json = json.dumps(payload, separators=(",", ":"))
    if "</script" in data_json:
        # Defensive: a subject/preview containing this sequence would break
        # out of the <script> block. Split it so the browser still parses
        # it as plain JSON text, not markup.
        data_json = data_json.replace("</script", "<\\/script")
    return _DASHBOARD_TEMPLATE.replace("__DATA__", data_json)


def _dashboard_payload(tiered: dict, meta: dict, drafts: dict[str, dict]) -> dict:
    scan_dt: datetime = meta.get("scan_dt", datetime.now(timezone.utc))
    all_emails = [e for tier in tiered.values() for e in tier]
    total = len(all_emails)

    items = [_dashboard_item(e, drafts) for e in all_emails]

    return {
        "meta": {
            "scan_iso": scan_dt.isoformat(),
            "folder": meta.get("folder", "Inbox"),
            "since_hours": meta.get("since_hours", 24),
            "scored": total,
            "fetched": meta.get("total_count", total),
            "unread": sum(1 for e in all_emails if not e.get("is_read")),
            "attachments": sum(1 for e in all_emails if e.get("has_attachments")),
            "high_importance": sum(
                1 for e in all_emails if (e.get("importance") or "").lower() == "high"
            ),
            "user_name": meta.get("user_display_name", "there"),
            "counts": {t: len(tiered.get(t, [])) for t in ("P1", "P2", "P3", "P4")},
            "incomplete": bool(meta.get("incomplete")),
            "incomplete_reason": meta.get("incomplete_reason", ""),
        },
        "items": items,
    }


def _dashboard_item(e: dict, drafts: dict[str, dict]) -> dict:
    signals = [
        {"s": s.get("signal"), "c": round(float(s.get("contribution", 0)), 1)}
        for s in e.get("top_3_signals", [])
    ]
    item = {
        "id": e.get("id", ""),
        "tier": e.get("priority_tier", "P4"),
        "subject": e.get("subject", ""),
        "from_name": e.get("from_name", ""),
        "from_email": e.get("from_email", ""),
        "received_at": _iso(e.get("received_at")),
        "importance": e.get("importance", "normal"),
        "has_attachments": bool(e.get("has_attachments")),
        "is_read": bool(e.get("is_read")),
        "body_preview": e.get("body_preview", ""),
        "score": round(float(e.get("urgency_score", 0)), 1),
        "signals": signals,
        "relationship": e.get("sender_relationship", "unknown"),
        "action": e.get("suggested_action", ""),
        "tone": e.get("reply_tone", ""),
        "effort": e.get("effort_estimate", ""),
        "thread_depth": e.get("thread_depth", 1),
        "web_link": e.get("web_link", ""),
        "promoted": bool(e.get("keyword_promoted")),
        "promoted_by": e.get("promoted_by", ""),
        "confidence": e.get("confidence", "medium"),
        "directed": bool(e.get("directed")),
        "recipient_count": e.get("recipient_count", 0),
        "attn_kind": e.get("attn_kind", ""),
        "attn_reason": e.get("attn_reason", ""),
    }
    draft = drafts.get(item["id"])
    if draft and draft.get("draft_weblink"):
        item["draft"] = {"web_link": draft["draft_weblink"]}
    return item


def _iso(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


_DASHBOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email Triage — EmailPrioritizationAgent</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --font-head:"Sora",system-ui,-apple-system,"Segoe UI",sans-serif;
  --font-body:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --violet:#7c5cfc; --indigo:#6366f1; --cyan:#06b6d4; --green:#10b981; --amber:#f59e0b; --pink:#ec4899;
  /* status (validated dataviz status palette) */
  --p1:#d03b3b; --p2:#ec835a; --p3:#eda100; --p4:#64748b;
  /* categorical (validated dataviz slots 1-6) */
  --c1:#2a78d6; --c2:#008300; --c3:#e87ba4; --c4:#eda100; --c5:#1baf7a; --c6:#eb6834;
}
:root[data-theme="light"]{
  --bg1:#f4f2ff; --bg2:#eef8ff; --bg3:#fef6fb;
  --card:#ffffff; --card-2:#faf9ff;
  --ink:#171532; --ink-2:#565478; --muted:#8b89a6;
  --line:rgba(23,21,50,.09); --line-2:rgba(23,21,50,.06);
  --shadow:0 1px 2px rgba(23,21,50,.04),0 8px 24px rgba(89,73,196,.08);
  --shadow-lg:0 2px 6px rgba(23,21,50,.05),0 18px 48px rgba(89,73,196,.14);
  --chip:#f2f0fb;
}
:root[data-theme="dark"]{
  --bg1:#0d0b1a; --bg2:#0b1220; --bg3:#150e1c;
  --card:#17152a; --card-2:#1d1a35;
  --ink:#f4f3ff; --ink-2:#b9b6d6; --muted:#7d7a9c;
  --line:rgba(255,255,255,.10); --line-2:rgba(255,255,255,.06);
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);
  --shadow-lg:0 2px 8px rgba(0,0,0,.5),0 22px 60px rgba(0,0,0,.5);
  --chip:#231f3f;
  /* dark categorical steps (validated for dark surface) */
  --c1:#3987e5; --c2:#008300; --c3:#d55181; --c4:#c98500; --c5:#199e70; --c6:#d95926;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:var(--font-body); color:var(--ink);
  background:
    radial-gradient(1200px 600px at 12% -8%, var(--bg1), transparent 60%),
    radial-gradient(1000px 620px at 100% 0%, var(--bg2), transparent 55%),
    radial-gradient(900px 700px at 50% 120%, var(--bg3), transparent 60%),
    var(--card-2);
  background-attachment:fixed;
  min-height:100vh; line-height:1.45; -webkit-font-smoothing:antialiased;
}
h1,h2,h3,.num{font-family:var(--font-head); letter-spacing:-.01em}
a{color:inherit}
.wrap{max-width:1240px; margin:0 auto; padding:22px 22px 64px}

.fade{opacity:0; transform:translateY(10px); animation:rise .55s cubic-bezier(.2,.7,.2,1) forwards}
@keyframes rise{to{opacity:1; transform:none}}

header.top{display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom:20px}
.avatar{width:52px;height:52px;border-radius:16px;flex:none;display:grid;place-items:center;
  font-family:var(--font-head);font-weight:700;font-size:22px;color:#fff;
  background:linear-gradient(135deg,var(--violet),var(--cyan));box-shadow:0 8px 20px rgba(124,92,252,.4)}
.greet{flex:1 1 auto;min-width:240px}
.greet h1{margin:0;font-size:26px;font-weight:700}
.greet h1 .nm{background:linear-gradient(90deg,var(--violet),var(--indigo),var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent}
.greet .sub{color:var(--ink-2);font-size:13.5px;margin-top:3px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.dot{width:4px;height:4px;border-radius:50%;background:var(--muted);display:inline-block}
.hbtns{display:flex;gap:9px;flex-wrap:wrap}
.btn{font-family:var(--font-body);font-weight:600;font-size:13px;border:1px solid var(--line);
  background:var(--card);color:var(--ink);padding:9px 14px;border-radius:12px;cursor:pointer;
  box-shadow:var(--shadow);transition:transform .12s ease, box-shadow .12s ease}
.btn:hover{transform:translateY(-1px);box-shadow:var(--shadow-lg)}
.btn.primary{background:linear-gradient(135deg,var(--violet),var(--indigo));color:#fff;border:none}
.btn.ghost{background:transparent;box-shadow:none}

.incband{margin-bottom:16px;background:rgba(237,161,0,.12);border:1px solid rgba(237,161,0,.3);border-left:4px solid var(--p3);border-radius:14px;padding:12px 16px;font-size:13px;color:var(--ink-2);display:none}
.incband.on{display:block}
.incband b{color:var(--ink)}
.waiting{margin-bottom:18px}
.wtitle{display:flex;align-items:center;gap:10px;margin:0 2px 12px}
.wtitle h2{font-size:17px;margin:0;font-weight:700;display:flex;align-items:center;gap:9px}
.wtitle .pill{background:linear-gradient(135deg,var(--violet),var(--indigo));color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px}
.wtitle .sub{color:var(--ink-2);font-size:12.5px;margin-left:auto}
.awaitlist{display:flex;flex-direction:column;gap:10px;margin-top:12px}
.arow{display:flex;align-items:center;gap:13px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--violet);border-radius:15px;padding:13px 15px;box-shadow:var(--shadow);cursor:pointer;transition:transform .12s,box-shadow .12s}
.arow:hover{transform:translateY(-1px);box-shadow:var(--shadow-lg)}
.arow .senav{width:40px;height:40px;border-radius:12px}
.arow .mid{flex:1 1 auto;min-width:0}
.arow .subj{font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.arow .l2{color:var(--ink-2);font-size:12.5px;margin-top:3px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.rchip{font-size:11px;font-weight:800;padding:4px 9px;border-radius:8px;white-space:nowrap;letter-spacing:.02em}
.rk-reply{background:rgba(99,102,241,.14);color:var(--indigo)}
.rk-meeting{background:rgba(124,92,252,.14);color:var(--violet)}
.rk-fyi{background:var(--chip);color:var(--ink-2)}
.rk-cancel{background:rgba(208,59,59,.12);color:var(--p1)}
.arow .inst{font-size:10.5px;font-weight:700;color:var(--muted);background:var(--chip);padding:2px 7px;border-radius:6px}
.tome{font-size:10.5px;font-weight:700;color:var(--green);background:rgba(16,185,129,.14);padding:2px 7px;border-radius:6px}
.draftready{font-size:10.5px;font-weight:700;color:var(--indigo);background:rgba(99,102,241,.14);padding:2px 7px;border-radius:6px}
.urgentnote{margin:12px 4px 0;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--p3);border-radius:14px;padding:12px 15px;font-size:12.5px;color:var(--ink-2);box-shadow:var(--shadow)}
.urgentnote b{color:var(--ink);font-weight:700}
.arow .go{flex:none;font-family:var(--font-body);font-weight:700;font-size:12px;color:var(--violet);background:var(--chip);border:none;padding:8px 12px;border-radius:10px;cursor:pointer;white-space:nowrap}
.arow .ascore{flex:none;font-family:var(--font-head);font-weight:800;font-size:16px;min-width:44px;text-align:right}

.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.kpi .cap{font-size:12.5px;color:var(--ink-2);font-weight:600;display:flex;align-items:center;gap:8px}
.kpi .val{font-size:34px;font-weight:800;margin-top:6px;line-height:1}
.kpi .foot{font-size:11.5px;color:var(--muted);margin-top:6px}
.kpi .ic{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;font-size:15px}
.kpi .bar{position:absolute;left:0;bottom:0;height:4px;width:100%}

.grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:18px;align-items:start}
.grid>*{min-width:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}
.card .hd{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:16px 18px 10px}
.card .hd h3{margin:0;font-size:15.5px;font-weight:700;display:flex;align-items:center;gap:9px}
.card .hd .meta{font-size:12px;color:var(--muted);font-weight:600}

.band{display:flex;align-items:center;gap:10px;padding:12px 18px;margin:2px 0;position:sticky;top:0}
.band .lbl{font-family:var(--font-head);font-weight:700;font-size:13px;letter-spacing:.02em}
.band .cnt{font-size:12px;color:var(--muted);font-weight:600}
.tierdot{width:10px;height:10px;border-radius:3px}

.rows{padding:4px 12px 12px}
.row{display:flex;gap:13px;padding:13px 12px;border-radius:14px;cursor:pointer;border:1px solid transparent;transition:background .12s,border-color .12s,transform .12s}
.row:hover{background:var(--card-2);border-color:var(--line-2);transform:translateX(2px)}
.row .rail{width:4px;border-radius:4px;flex:none}
.senav{width:38px;height:38px;border-radius:11px;flex:none;display:grid;place-items:center;color:#fff;font-weight:700;font-size:14px;font-family:var(--font-head)}
.row .mid{flex:1 1 auto;min-width:0}
.row .subj{font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px;min-width:0}
.row .subj .txt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .line2{color:var(--ink-2);font-size:12.5px;margin-top:2px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.row .sigs{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.sig{font-size:11px;font-weight:600;background:var(--chip);color:var(--ink-2);padding:3px 8px;border-radius:7px;white-space:nowrap}
.sig b{color:var(--ink);font-weight:700}
.row .right{flex:none;text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:8px;min-width:96px}
.scorewrap{width:92px}
.scorewrap .n{font-family:var(--font-head);font-weight:800;font-size:18px;line-height:1}
.scorewrap .track{height:6px;border-radius:6px;background:var(--chip);margin-top:5px;overflow:hidden}
.scorewrap .fill{height:100%;border-radius:6px}
.actpill{font-size:11px;font-weight:700;padding:5px 9px;border-radius:8px;white-space:nowrap}
.badge{font-size:10px;font-weight:800;letter-spacing:.04em;padding:3px 7px;border-radius:6px;text-transform:uppercase}
.tag{font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:6px;display:inline-flex;align-items:center;gap:4px}
.tag.unread{background:rgba(124,92,252,.14);color:var(--violet)}
.tag.att{background:var(--chip);color:var(--ink-2)}
.tag.hi{background:rgba(208,59,59,.12);color:var(--p1)}
.tag.auto{background:rgba(237,161,0,.16);color:#9a6b00}
:root[data-theme="dark"] .tag.auto{color:#f3c04d}
.collapsed .rows{display:none}
.toggle{cursor:pointer;user-select:none;color:var(--violet);font-size:12px;font-weight:700;background:none;border:none;font-family:var(--font-body)}

.rail-cards{display:flex;flex-direction:column;gap:18px}
.legend{padding:6px 18px 18px}
.lg{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:13px;border-top:1px solid var(--line-2)}
.lg:first-child{border-top:none}
.lg .sw{width:11px;height:11px;border-radius:4px;flex:none}
.lg .nm{flex:1 1 auto;font-weight:600}
.lg .ct{font-weight:700;font-variant-numeric:tabular-nums}
.lg .pc{color:var(--muted);font-size:12px;width:42px;text-align:right;font-variant-numeric:tabular-nums}
.donut-wrap{display:grid;place-items:center;padding:8px 0 2px}
.tierbar{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:2px 18px 12px;gap:2px;background:transparent}
.tierbar span{height:100%}
.tstats{display:flex;gap:8px;padding:0 18px 16px;flex-wrap:wrap}
.tstat{flex:1 1 60px;background:var(--card-2);border:1px solid var(--line-2);border-radius:12px;padding:9px 10px;text-align:center}
.tstat .n{font-family:var(--font-head);font-weight:800;font-size:20px}
.tstat .l{font-size:10.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.scan{padding:6px 18px 18px;font-size:12.5px;color:var(--ink-2)}
.scan .r{display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid var(--line-2)}
.scan .r:first-child{border-top:none}
.scan .r b{color:var(--ink);font-weight:700}
.note{margin:0 18px 16px;background:rgba(237,161,0,.10);border:1px solid rgba(237,161,0,.25);border-radius:12px;padding:11px 13px;font-size:12px;color:var(--ink-2)}
.note b{color:var(--ink)}

.ov{position:fixed;inset:0;background:rgba(15,12,35,.5);backdrop-filter:blur(3px);display:none;align-items:center;justify-content:center;padding:20px;z-index:50}
.ov.on{display:flex}
.modal{background:var(--card);border-radius:22px;max-width:640px;width:100%;max-height:88vh;overflow:auto;box-shadow:var(--shadow-lg);border:1px solid var(--line)}
.modal .mh{padding:20px 22px 14px;border-bottom:1px solid var(--line-2);position:relative}
.modal .mh .badge{margin-bottom:8px;display:inline-block}
.modal .mh h2{font-size:19px;margin:0 0 8px}
.modal .mh .from{font-size:13px;color:var(--ink-2)}
.modal .mb{padding:16px 22px 6px}
.mblock{margin-bottom:16px}
.mblock .t{font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:7px;display:flex;align-items:center;gap:7px}
.mblock .txt{font-size:14px;color:var(--ink);background:var(--card-2);border:1px solid var(--line-2);border-radius:12px;padding:13px 15px;line-height:1.55}
.whygrid{display:flex;gap:8px;flex-wrap:wrap}
.whychip{font-size:12px;font-weight:600;background:var(--chip);padding:7px 11px;border-radius:10px}
.whychip b{font-family:var(--font-head)}
.recgrid{display:flex;gap:10px;flex-wrap:wrap}
.rec{flex:1 1 120px;background:var(--card-2);border:1px solid var(--line-2);border-radius:12px;padding:11px 13px}
.rec .l{font-size:10.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.rec .v{font-weight:700;font-size:14px;margin-top:3px;text-transform:capitalize}
.mf{padding:12px 22px 20px;display:flex;gap:10px;justify-content:flex-end;position:sticky;bottom:0;background:linear-gradient(to top,var(--card),var(--card) 70%,transparent)}
.close{position:absolute;top:16px;right:18px;background:var(--chip);border:none;width:32px;height:32px;border-radius:10px;cursor:pointer;font-size:16px;color:var(--ink-2)}

.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--card);font-size:12px;font-weight:600;padding:6px 9px;border-radius:8px;opacity:0;transition:opacity .1s;z-index:60;white-space:nowrap}
.footer{text-align:center;color:var(--muted);font-size:12px;margin-top:26px}

@media(max-width:980px){
  .grid{grid-template-columns:1fr}
  .kpis{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:560px){.kpis{grid-template-columns:1fr 1fr}.row .sigs{display:none}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top fade" style="animation-delay:.02s">
    <div class="avatar" id="ava">A</div>
    <div class="greet">
      <h1 id="greet">Good day <span class="nm">there</span> 👋</h1>
      <div class="sub" id="submeta"></div>
    </div>
    <div class="hbtns">
      <button class="btn ghost" id="themeBtn" title="Toggle theme">🌙 Theme</button>
      <button class="btn" id="focusBtn">✋ Directed</button>
      <button class="btn primary" id="outlookBtn">↗ Open Outlook</button>
    </div>
  </header>

  <div class="incband" id="incBand"></div>

  <section class="waiting fade" style="animation-delay:.06s">
    <div class="wtitle">
      <h2>✋ Directed at You <span class="pill" id="wcount">0</span></h2>
      <span class="sub">sent to you personally or your small team — mass distribution lists excluded</span>
    </div>
    <div class="card"><div class="awaitlist" id="awaitlist" style="padding:8px"></div></div>
    <div class="urgentnote" id="urgentNote"></div>
  </section>

  <section class="kpis fade" style="animation-delay:.1s" id="kpis"></section>

  <div class="grid">
    <main class="card fade" style="animation-delay:.14s">
      <div class="hd">
        <h3>📥 Priority Inbox</h3>
        <span class="meta" id="inboxMeta"></span>
      </div>
      <div id="tiers"></div>
    </main>

    <aside class="rail-cards fade" style="animation-delay:.18s">
      <div class="card">
        <div class="hd"><h3>🍩 Inbox Breakdown</h3><span class="meta" id="catMeta"></span></div>
        <div class="donut-wrap"><div id="donut"></div></div>
        <div class="legend" id="catLegend"></div>
      </div>
      <div class="card">
        <div class="hd"><h3>📊 Priority Mix</h3><span class="meta">by tier</span></div>
        <div class="tierbar" id="tierbar"></div>
        <div class="tstats" id="tstats"></div>
        <div class="note" id="autoNote"></div>
      </div>
      <div class="card">
        <div class="hd"><h3>🔎 Scan Details</h3></div>
        <div class="scan" id="scan"></div>
      </div>
    </aside>
  </div>

  <div class="footer">Generated by <b>EmailPrioritizationAgent</b> · Microsoft 365 connector (read-only) · multi-signal urgency model</div>
</div>

<div class="ov" id="ov"><div class="modal" id="modal"></div></div>
<div class="tip" id="tip"></div>

<script>
const RAW = __DATA__;
</script>
<script>
(function(){
  "use strict";
  const $=(s,r=document)=>r.querySelector(s);
  const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
  const esc=s=>(s==null?"":String(s)).replace(/[&<>"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
  const META=RAW.meta, ITEMS=RAW.items;
  const SCAN=new Date(META.scan_iso);

  const TIER={
    P1:{c:"var(--p1)",lbl:"Respond now",name:"P1 · Critical",ic:"🔴"},
    P2:{c:"var(--p2)",lbl:"Respond today",name:"P2 · High",ic:"🟠"},
    P3:{c:"var(--p3)",lbl:"This week",name:"P3 · Medium",ic:"🟡"},
    P4:{c:"var(--p4)",lbl:"When time allows",name:"P4 · Low",ic:"⚪"}
  };
  const AVCOL=["#7c5cfc","#6366f1","#06b6d4","#10b981","#f59e0b","#ec4899","#2a78d6","#eb6834","#e34948","#1baf7a"];
  const avColor=s=>AVCOL[Math.abs(hash(s||"?"))%AVCOL.length];
  function hash(s){let h=0;for(let i=0;i<s.length;i++){h=(h<<5)-h+s.charCodeAt(i)|0;}return h;}
  const SIGLBL={recency:"Recency",action_language:"Action lang.",sender_authority:"Sender",thread_depth:"Thread",importance_flag:"Importance",has_attachment:"Attachment"};

  function initials(name,email){
    let n=(name||email||"?").trim();
    let p=n.split(/[\s.@_]+/).filter(Boolean);
    return ((p[0]?.[0]||"")+(p[1]?.[0]||"")).toUpperCase()||n[0].toUpperCase();
  }
  function ago(iso){
    const d=new Date(iso); let m=Math.round((SCAN-d)/60000);
    if(m<0)m=0;
    if(m<60)return m+"m ago";
    const h=Math.round(m/60); if(h<24)return h+"h ago";
    return Math.round(h/24)+"d ago";
  }
  function timeStr(iso){try{return new Date(iso).toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});}catch(e){return iso;}}

  // Categories are derived from already-computed pipeline fields (attn_kind,
  // sender_relationship, subject/body keywords) rather than hardcoded example
  // subjects, so this holds up on future runs with different mail.
  function categorize(it){
    const s=(it.subject||"").toLowerCase(), b=(it.body_preview||"").toLowerCase(), t=s+" "+b;
    if(it.attn_kind==="meeting"||it.attn_kind==="cancel"||/microsoft teams meeting/.test(b))return"Meetings & Invites";
    if(it.attn_kind==="reply"||/action required|action needed|approval needed|your input needed|please review/.test(s))return"Action Needed";
    if(/\b(deploy|pipeline|build|release|sprint|ci\/cd|jenkins|feature branch)\b/.test(t))return"Deployments & CI";
    if(it.relationship==="unknown"&&/report|usage|alert|summary|dashboard|scan (completed|results)/.test(s))return"Ops Reports";
    if(it.relationship==="unknown")return"Announcements";
    return"Threads & Discussion";
  }
  const CATS=["Deployments & CI","Ops Reports","Action Needed","Meetings & Invites","Announcements","Threads & Discussion"];
  const CATCOL={"Deployments & CI":"var(--c1)","Ops Reports":"var(--c2)","Action Needed":"var(--c3)","Meetings & Invites":"var(--c4)","Announcements":"var(--c5)","Threads & Discussion":"var(--c6)"};

  /* ---- incomplete-scan banner ---- */
  if(META.incomplete){
    $("#incBand").classList.add("on");
    $("#incBand").innerHTML="⚠️ <b>Incomplete scan:</b> "+esc(META.incomplete_reason||"Some emails could not be fetched.");
  }

  /* ---- header ---- */
  const uName=(META.user_name||"there").split(" ")[0];
  const hr=SCAN.getUTCHours()+5.5;
  const part=hr<12?"morning":hr<17?"afternoon":"evening";
  $("#greet").innerHTML='Good '+part+', <span class="nm">'+esc(uName)+'</span> 👋';
  $("#ava").textContent=(uName[0]||"?").toUpperCase();
  $("#submeta").innerHTML=
    '📅 '+SCAN.toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric",year:"numeric"})+
    ' <span class="dot"></span> 📁 '+esc(META.folder)+
    ' <span class="dot"></span> ⏱ last '+META.since_hours+'h'+
    ' <span class="dot"></span> '+META.scored+' emails';

  /* ---- Directed at You (mail addressed to you personally / small team) ---- */
  const RKC={reply:"rk-reply",meeting:"rk-meeting",fyi:"rk-fyi",cancel:"rk-cancel",attn:"rk-fyi"};
  const nsub=s=>(s||"").replace(/^(re|fw|fwd):\s*/i,"").trim().toLowerCase();
  const dmap=new Map();
  ITEMS.filter(x=>x.directed).forEach(it=>{
    const k=nsub(it.subject), cur=dmap.get(k);
    if(!cur)dmap.set(k,{rep:it,count:1,maxRecip:it.recipient_count||0});
    else{cur.count++; if(it.score>cur.rep.score)cur.rep=it; if((it.recipient_count||0)>cur.maxRecip)cur.maxRecip=it.recipient_count;}
  });
  const threads=[...dmap.values()].sort((a,b)=>{
    const ra=a.rep.attn_kind==="reply"?1:0, rb=b.rep.attn_kind==="reply"?1:0;
    return (rb-ra)||(b.rep.score-a.rep.score);
  });
  $("#wcount").textContent=threads.length;
  const dMap=[];
  $("#awaitlist").innerHTML=threads.length?threads.map(th=>{
    const it=th.rep, gi=dMap.push(it)-1, t=TIER[it.tier];
    const n=Math.max(0,(th.maxRecip||1)-1);
    const hasDraft=!!it.draft;
    return '<div class="arow" data-aw="'+gi+'" style="border-left-color:'+t.c+'">'+
      '<div class="senav" style="background:'+avColor(it.from_email)+'">'+esc(initials(it.from_name,it.from_email))+'</div>'+
      '<div class="mid"><div class="subj">'+esc(it.subject.replace(/^(re|fw|fwd):\s*/i,""))+'</div>'+
        '<div class="l2"><span class="rchip '+(RKC[it.attn_kind]||"rk-fyi")+'">'+esc(it.attn_reason)+'</span>'+
        '<b>'+esc(it.from_name||it.from_email)+'</b> <span class="dot"></span> '+ago(it.received_at)+
        ' <span class="tome">👤 you + '+n+(n===1?' other':' others')+'</span>'+
        (hasDraft?' <span class="draftready">📝 draft ready</span>':'')+
        (th.count>1?' <span class="inst">'+th.count+' msgs</span>':'')+'</div></div>'+
      '<div class="ascore" style="color:'+t.c+'">'+it.score+'</div>'+
      '<button class="go">'+(hasDraft?'📝 Draft ready ↗':'Open ↗')+'</button></div>';
  }).join(""):'<div style="padding:18px;text-align:center;color:var(--muted);font-size:13px">No email was addressed to you personally in this window — everything came via distribution lists. See the full Priority Inbox below.</div>';
  $("#awaitlist").querySelectorAll(".arow").forEach(r=>{
    const it=dMap[+r.dataset.aw];
    r.addEventListener("click",()=>openModal(it));
    r.querySelector(".go").addEventListener("click",e=>{
      e.stopPropagation();
      window.open(it.draft?it.draft.web_link:it.web_link,"_blank");
    });
  });
  const topUrgent=[...ITEMS].sort((a,b)=>b.score-a.score).find(x=>!x.directed && /^Reply/.test(x.action||""));
  if(topUrgent){
    $("#urgentNote").innerHTML='⚠️ <b>Heads-up:</b> your most urgent email overall — “'+esc(topUrgent.subject)+'” ('+topUrgent.tier+', score '+topUrgent.score+', from '+esc(topUrgent.from_name||topUrgent.from_email)+') — went to <b>'+(topUrgent.recipient_count||"a large group of")+' recipients</b>, so it is not counted as personally addressed. Find it in your <b>Priority Inbox</b> below.';
  } else { $("#urgentNote").style.display="none"; }

  /* ---- KPIs ---- */
  const KPI=[
    {cap:"Directed at You",ic:"✋",bg:"rgba(208,59,59,.12)",col:"var(--p1)",val:threads.length,foot:"addressed to you / your team"},
    {cap:"Unread",ic:"✉️",bg:"rgba(99,102,241,.12)",col:"var(--indigo)",val:META.unread,foot:"of "+META.scored+" in window"},
    {cap:"High Importance",ic:"❗",bg:"rgba(236,72,153,.12)",col:"var(--pink)",val:META.high_importance,foot:"flagged by sender"},
    {cap:"With Attachments",ic:"📎",bg:"rgba(6,182,212,.12)",col:"var(--cyan)",val:META.attachments,foot:"files to review"}
  ];
  $("#kpis").innerHTML=KPI.map(k=>
    '<div class="kpi"><div class="cap"><span class="ic" style="background:'+k.bg+';color:'+k.col+'">'+k.ic+'</span>'+k.cap+'</div>'+
    '<div class="val" style="color:'+k.col+'" data-count="'+k.val+'">0</div><div class="foot">'+esc(k.foot)+'</div>'+
    '<div class="bar" style="background:'+k.col+';opacity:.35"></div></div>').join("");
  document.querySelectorAll(".kpi .val").forEach(v=>{
    const target=+v.dataset.count; let cur=0; const step=Math.max(1,Math.ceil(target/28));
    const t=setInterval(()=>{cur+=step;if(cur>=target){cur=target;clearInterval(t);}v.textContent=cur;},22);
  });

  /* ---- Priority Inbox tiers ---- */
  const byTier={P1:[],P2:[],P3:[],P4:[]};
  ITEMS.forEach(it=>byTier[it.tier].push(it));
  Object.keys(byTier).forEach(t=>byTier[t].sort((a,b)=>b.score-a.score));
  $("#inboxMeta").textContent=ITEMS.length+" scored · ranked by urgency";

  const SCOREMAX=70;
  function rowHTML(it,i){
    const t=TIER[it.tier];
    const sigs=(it.signals||[]).map(s=>'<span class="sig">'+ (SIGLBL[s.s]||s.s) +' <b>+'+s.c+'</b></span>').join("");
    const tags=
      (!it.is_read?'<span class="tag unread">● unread</span>':'')+
      (it.importance==="high"?'<span class="tag hi">❗ high</span>':'')+
      (it.has_attachments?'<span class="tag att">📎</span>':'')+
      (it.promoted?'<span class="tag auto" title="Auto-promoted because keyword \''+esc(it.promoted_by)+'\' appeared">🏷 '+esc(it.promoted_by)+'</span>':'');
    const w=Math.max(6,Math.min(100,Math.round(it.score/SCOREMAX*100)));
    return '<div class="row" data-idx="'+i+'" data-tier="'+it.tier+'">'+
      '<div class="rail" style="background:'+t.c+'"></div>'+
      '<div class="senav" style="background:'+avColor(it.from_email)+'">'+esc(initials(it.from_name,it.from_email))+'</div>'+
      '<div class="mid">'+
        '<div class="subj"><span class="txt">'+esc(it.subject)+'</span></div>'+
        '<div class="line2"><b>'+esc(it.from_name||it.from_email)+'</b> <span class="dot"></span> '+ago(it.received_at)+' '+tags+'</div>'+
        '<div class="sigs">'+sigs+'</div>'+
      '</div>'+
      '<div class="right">'+
        '<div class="scorewrap"><div class="n" style="color:'+t.c+'">'+it.score+'</div>'+
          '<div class="track"><div class="fill" style="width:'+w+'%;background:'+t.c+'"></div></div></div>'+
        '<span class="actpill" style="background:'+t.c+'1f;color:'+t.c+'">'+esc(it.action)+'</span>'+
      '</div></div>';
  }

  let idxMap=[];
  const tiersEl=$("#tiers");
  ["P1","P2","P3","P4"].forEach(t=>{
    const list=byTier[t]; if(!list.length)return;
    const sec=el("section","tsec"+(t==="P4"||t==="P3"?" collapsed":""));
    const band=el("div","band");
    band.style.background="linear-gradient(90deg,"+TIER[t].c+"14,transparent)";
    band.innerHTML='<span class="tierdot" style="background:'+TIER[t].c+'"></span>'+
      '<span class="lbl" style="color:'+TIER[t].c+'">'+TIER[t].name+'</span>'+
      '<span class="cnt">· '+TIER[t].lbl+'</span>'+
      '<span style="flex:1"></span><span class="cnt">'+list.length+'</span>';
    sec.appendChild(band);
    const rows=el("div","rows");
    rows.innerHTML=list.map(it=>{const gi=idxMap.push(it)-1;return rowHTML(it,gi);}).join("");
    sec.appendChild(rows);
    if(t==="P3"||t==="P4"){
      const tg=el("button","toggle","▸ Show "+list.length+" "+t+" items");
      tg.style.margin="0 0 10px 20px";
      tg.onclick=()=>{const c=sec.classList.toggle("collapsed");tg.textContent=(c?"▸ Show ":"▾ Hide ")+list.length+" "+t+" items";};
      sec.insertBefore(tg,rows);
    }
    tiersEl.appendChild(sec);
  });
  tiersEl.querySelectorAll(".row").forEach(r=>{
    r.addEventListener("click",()=>openModal(idxMap[+r.dataset.idx]));
  });

  /* ---- Category doughnut (inline SVG) ---- */
  const catCounts={}; CATS.forEach(c=>catCounts[c]=0);
  ITEMS.forEach(it=>{catCounts[categorize(it)]++;});
  const total=ITEMS.length||1;
  const R=64,SW=26,C=90,circ=2*Math.PI*R;
  let off=0; const segs=[];
  const tip=$("#tip");
  CATS.forEach(cat=>{
    const v=catCounts[cat]; if(!v)return;
    const frac=v/total, len=frac*circ, gap=2;
    segs.push({cat,v,frac,dash:Math.max(0,len-gap),off});
    off+=len;
  });
  const arcs=segs.map(s=>
    '<circle r="'+R+'" cx="'+C+'" cy="'+C+'" fill="none" stroke="'+CATCOL[s.cat]+'" stroke-width="'+SW+'" '+
    'stroke-dasharray="'+s.dash+' '+(circ-s.dash)+'" stroke-dashoffset="'+(-s.off)+'" '+
    'data-cat="'+esc(s.cat)+'" data-v="'+s.v+'" style="transition:opacity .12s;cursor:pointer"></circle>').join("");
  $("#donut").innerHTML='<svg width="180" height="180" viewBox="0 0 180 180" style="transform:rotate(-90deg)">'+arcs+'</svg>';
  const dw=$("#donut"); dw.style.position="relative";
  const ctr=el("div"); ctr.style.cssText="position:absolute;inset:0;display:grid;place-items:center;pointer-events:none;text-align:center";
  ctr.innerHTML='<div><div style="font-family:var(--font-head);font-weight:800;font-size:30px;line-height:1">'+ITEMS.length+'</div>'+
    '<div style="font-size:11px;color:var(--muted);font-weight:600;margin-top:2px">emails</div></div>';
  dw.appendChild(ctr);
  $("#catMeta").textContent=CATS.filter(c=>catCounts[c]).length+" categories";
  $("#catLegend").innerHTML=CATS.filter(c=>catCounts[c]).map(c=>
    '<div class="lg" data-cat="'+esc(c)+'"><span class="sw" style="background:'+CATCOL[c]+'"></span>'+
    '<span class="nm">'+esc(c)+'</span><span class="ct">'+catCounts[c]+'</span>'+
    '<span class="pc">'+Math.round(catCounts[c]/total*100)+'%</span></div>').join("");
  function hi(cat){
    dw.querySelectorAll("circle").forEach(c=>c.style.opacity=(!cat||c.dataset.cat===cat)?"1":"0.25");
    $("#catLegend").querySelectorAll(".lg").forEach(l=>l.style.opacity=(!cat||l.dataset.cat===cat)?"1":"0.4");
  }
  dw.querySelectorAll("circle").forEach(c=>{
    c.addEventListener("mousemove",e=>{tip.style.opacity="1";tip.textContent=c.dataset.cat+": "+c.dataset.v+" ("+Math.round(c.dataset.v/total*100)+"%)";tip.style.left=(e.clientX+12)+"px";tip.style.top=(e.clientY-10)+"px";});
    c.addEventListener("mouseenter",()=>hi(c.dataset.cat));
    c.addEventListener("mouseleave",()=>{tip.style.opacity="0";hi(null);});
  });
  $("#catLegend").querySelectorAll(".lg").forEach(l=>{
    l.addEventListener("mouseenter",()=>hi(l.dataset.cat));
    l.addEventListener("mouseleave",()=>hi(null));
  });

  /* ---- tier mix bar ---- */
  const tb=$("#tierbar");
  ["P1","P2","P3","P4"].forEach(t=>{
    const v=META.counts[t]; if(!v)return;
    const s=el("span"); s.style.flex=v+" 1 0"; s.style.background=TIER[t].c;
    s.title=TIER[t].name+": "+v;
    s.addEventListener("mousemove",e=>{tip.style.opacity="1";tip.textContent=TIER[t].name+": "+v;tip.style.left=(e.clientX+12)+"px";tip.style.top=(e.clientY-10)+"px";});
    s.addEventListener("mouseleave",()=>tip.style.opacity="0");
    tb.appendChild(s);
  });
  $("#tstats").innerHTML=["P1","P2","P3","P4"].map(t=>
    '<div class="tstat"><div class="n" style="color:'+TIER[t].c+'">'+META.counts[t]+'</div><div class="l">'+t+'</div></div>').join("");
  const promotedCount=ITEMS.filter(x=>x.promoted).length;
  if(promotedCount>0){
    $("#autoNote").innerHTML='🏷 <b>'+promotedCount+' item'+(promotedCount!==1?'s':'')+'</b> were keyword-promoted (e.g. a "critical"/"urgent" match in the text) — skim the 🏷 tag before treating one as a true fire.';
  } else {
    $("#autoNote").style.display="none";
  }

  /* ---- scan card ---- */
  $("#scan").innerHTML=
    row2("Mailbox folder","<b>"+esc(META.folder)+"</b>")+
    row2("Look-back window","<b>"+META.since_hours+" hours</b>")+
    row2("Scored","<b>"+META.scored+"</b> emails")+
    row2("Scan time","<b>"+SCAN.toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})+"</b>")+
    row2("Mode","<b>read-only</b>");
  function row2(a,b){return '<div class="r"><span>'+a+'</span><span>'+b+'</span></div>';}

  /* ---- modal ---- */
  function openModal(it){
    const t=TIER[it.tier];
    const why=(it.signals||[]).map(s=>'<span class="whychip">'+(SIGLBL[s.s]||s.s)+' <b style="color:'+t.c+'">+'+s.c+'</b></span>').join("");
    $("#modal").innerHTML=
      '<button class="close" id="mClose">✕</button>'+
      '<div class="mh">'+
        '<span class="badge" style="background:'+t.c+'1f;color:'+t.c+'">'+t.name+' · '+esc(it.action)+'</span>'+
        '<h2>'+esc(it.subject)+'</h2>'+
        '<div class="from">from <b>'+esc(it.from_name||it.from_email)+'</b> &lt;'+esc(it.from_email)+'&gt;<br>'+timeStr(it.received_at)+' · '+ago(it.received_at)+' · '+esc(it.relationship)+' sender'+(it.thread_depth>1?' · thread depth '+it.thread_depth:'')+'</div>'+
      '</div>'+
      '<div class="mb">'+
        '<div class="mblock"><div class="t">📄 Preview <span style="color:var(--muted);font-weight:600;letter-spacing:0;text-transform:none">(first 200 chars)</span></div><div class="txt">'+esc(it.body_preview||"—")+'</div></div>'+
        '<div class="mblock"><div class="t">🧠 Why this ranked '+it.tier+' — score '+it.score+'</div><div class="whygrid">'+why+
          (it.promoted?'<span class="whychip" style="background:rgba(237,161,0,.16)">🏷 keyword floor: <b>'+esc(it.promoted_by)+'</b></span>':'')+
          '<span class="whychip">confidence: <b>'+esc(it.confidence)+'</b></span></div></div>'+
        '<div class="mblock"><div class="t">✅ Suggested handling</div><div class="recgrid">'+
          '<div class="rec"><div class="l">Action</div><div class="v">'+esc(it.action)+'</div></div>'+
          '<div class="rec"><div class="l">Reply tone</div><div class="v">'+esc(it.tone)+'</div></div>'+
          '<div class="rec"><div class="l">Effort</div><div class="v">'+esc(it.effort)+'</div></div>'+
        '</div></div>'+
      '</div>'+
      '<div class="mf"><button class="btn ghost" id="mCancel">Close</button>'+
        (it.draft?'<button class="btn" id="mDraft">📝 Open Draft ↗</button>':'')+
        '<button class="btn primary" id="mOpen">↗ Open in Outlook</button></div>';
    $("#ov").classList.add("on");
    $("#mClose").onclick=$("#mCancel").onclick=closeModal;
    $("#mOpen").onclick=()=>window.open(it.web_link,"_blank");
    if(it.draft) $("#mDraft").onclick=()=>window.open(it.draft.web_link,"_blank");
  }
  function closeModal(){$("#ov").classList.remove("on");}
  $("#ov").addEventListener("click",e=>{if(e.target===$("#ov"))closeModal();});
  document.addEventListener("keydown",e=>{if(e.key==="Escape")closeModal();});

  /* ---- header actions ---- */
  const root=document.documentElement;
  function applyTheme(m){root.setAttribute("data-theme",m);$("#themeBtn").innerHTML=(m==="dark"?"☀️ Light":"🌙 Dark");}
  let theme=(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";
  applyTheme(theme);
  $("#themeBtn").onclick=()=>{theme=(theme==="dark"?"light":"dark");applyTheme(theme);};
  $("#focusBtn").onclick=()=>{document.querySelector(".waiting").scrollIntoView({behavior:"smooth",block:"start"});};
  $("#outlookBtn").onclick=()=>window.open("https://outlook.office365.com/mail/inbox","_blank");
})();
</script>
</body>
</html>"""


# ── JSON ────────────────────────────────────────────────────────────────────

def _build_json(tiered: dict, meta: dict) -> str:
    scan_dt: datetime = meta.get("scan_dt", datetime.now(timezone.utc))
    payload = {
        "scan_datetime": scan_dt.isoformat(),
        "folder": meta.get("folder", "Inbox"),
        "since_hours": meta.get("since_hours", 24),
        "total_emails": meta.get("total_count", 0),
        "incomplete": meta.get("incomplete", False),
        "incomplete_reason": meta.get("incomplete_reason", ""),
        "tiers": {
            tier: [_serializable(e) for e in emails]
            for tier, emails in tiered.items()
        },
    }
    return json.dumps(payload, indent=2, default=str)


def _serializable(e: dict) -> dict:
    """Convert datetime objects to ISO strings for JSON serialization."""
    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in e.items()
    }


# ── Plain-text digest ────────────────────────────────────────────────────────

def _build_text(tiered: dict, meta: dict) -> str:
    scan_dt: datetime = meta.get("scan_dt", datetime.now(timezone.utc))
    date_str = scan_dt.strftime("%B %d, %Y  %H:%M UTC")
    lines = [f"📬 Email Triage — {date_str}", ""]

    p3_count = len(tiered.get("P3", []))
    p4_count = len(tiered.get("P4", []))

    for tier_key in ("P1", "P2"):
        emails = tiered.get(tier_key, [])
        if not emails:
            continue
        lines.append(f"{_TIER_LABEL[tier_key]} ({len(emails)})")
        for e in emails:
            sla = " [SLA↑]" if e.get("sla_promoted") else ""
            lines.append(
                f"  • [{e.get('from_name','')}] \"{e.get('subject','')}\" "
                f"— Score {e.get('urgency_score',0)}{sla}  [{e.get('suggested_action','')}]"
            )
        lines.append("")

    if p3_count or p4_count:
        lines.append(f"{p3_count} P3 + {p4_count} P4 emails de-prioritized.")

    if meta.get("incomplete"):
        lines.append(f"⚠️  Incomplete scan: {meta.get('incomplete_reason','')}")

    lines.append(f"\nFull report: reports/{scan_dt.strftime('%Y%m%d')}/email-triage.html")
    return "\n".join(lines)


# ── Special variants ─────────────────────────────────────────────────────────

def _inbox_clear_report(meta: dict) -> dict[str, str]:
    scan_dt: datetime = meta.get("scan_dt", datetime.now(timezone.utc))
    date_str = scan_dt.strftime("%B %d, %Y  %H:%M UTC")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Email Triage — {date_str}</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:60px auto;text-align:center;color:#424242}}</style>
</head><body>
<h1>📬 Email Triage — {date_str}</h1>
<div style="background:#e8f5e9;padding:24px;border-radius:8px;margin-top:40px">
  <h2 style="color:#2e7d32">✅ Inbox clear — no action required</h2>
  <p>No emails found in the last {meta.get('since_hours',24)} hours in folder
     <b>{meta.get('folder','Inbox')}</b>.</p>
</div>
<footer style="color:#9e9e9e;font-size:0.8em;margin-top:60px">
  EmailPrioritizationAgent — advisory only.</footer>
</body></html>"""
    txt = f"📬 Email Triage — {date_str}\n\n✅ Inbox clear — no action required.\n"
    js = json.dumps({"scan_datetime": scan_dt.isoformat(), "total_emails": 0,
                     "tiers": {"P1": [], "P2": [], "P3": [], "P4": []}}, indent=2)
    return {"html": html, "json": js, "text": txt}
