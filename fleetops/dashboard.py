"""Stage 2c — ONE-page observability dashboard, server-rendered HTML (no JS).

Renders the full ordered chain for an incident: timeline of hops with
timestamps, which agent did what (planner decision, gateway route+policy, tool
calls), memory recall events, and RED-highlighted rejected/blocked spans with
their reasons. Every hop row shows the active model id — the Gemini 3.x pin is
visible in the trace itself. Served by GET /trace/{incident_id} on the same
FastAPI app as everything else: works against local fakes (`make demo` prints
its URL; `make run`) and unchanged after GCP deploy.

ponytail: inline CSS, one template function — swap for React/HTMX only if a
second page ever needs to exist.
"""

from __future__ import annotations

import html as _html


def esc(x) -> str:
    return _html.escape(str(x), quote=True)


BLOCK_STEPS = {"gateway_rejected", "dispatch_rejected", "guardrail_blocked"}
MEMORY_STEPS = {"memory_read", "memory_write"}


def _time(ts: str) -> str:
    # 2026-08-29T16:40:12.345678+00:00 -> HH:MM:SS.mmm (+ date if not today-ish; keep it simple: always show)
    return ts[11:23] + "Z"  # demo data is UTC ISO


def _row(span: dict, model_id: str) -> str:
    step = span["step"]
    detail = span.get("detail") or {}
    blocked = step in BLOCK_STEPS or span.get("status") == "error"

    if step in ("gateway_route",):
        body = (f"{esc(detail.get('principal'))} ({esc(detail.get('role'))}) "
                f"{esc(detail.get('action'))} {esc(detail.get('capability') or '')} -> "
                f"<b>{esc(detail.get('target'))}</b> <span class='chip ok'>allow</span>")
    elif step == "gateway_rejected":
        body = (f"token {esc(detail.get('token'))}: "
                f"{esc(detail.get('action'))} {esc(detail.get('capability') or '')} — "
                f"<b>{esc(detail.get('reason'))}</b> <span class='chip deny'>deny</span>")
    elif step == "dispatch_rejected":
        body = (f"subtask {esc(detail.get('kind') or detail.get('task_id') or '')} / "
                f"{esc(detail.get('capability') or '')}: <b>{esc(detail.get('reason'))}</b> "
                f"<span class='chip deny'>blocked</span>")
    elif step == "guardrail_blocked":
        why = "<br>".join(f"&#10007; {esc(r)}" for r in (detail.get("reasons") or []))
        body = (f"tool <code>{esc(detail.get('tool'))}</code> never reached the agent: "
                f"{why} <span class='chip deny'>blocked</span>")
    elif step == "planner_plan":
        plan = detail.get("plan") or []
        sub = ", ".join(esc(t.get("kind")) for t in plan)
        body = f"decomposed into {len(plan)} subtasks ({sub}) <span class='chip ok'>ok</span>"
    elif step == "memory_read":
        entries = detail.get("entries") or []
        principal = esc(detail.get("principal"))
        if entries:
            first = esc(entries[0].get("text", ""))[:300]
            body = (f"recalled {len(entries)} prior entr{'y' if len(entries) == 1 else 'ies'} from "
                    f"<b>{principal}</b><div class='recall'>{first}…</div>")
        else:
            body = f"memory read — no prior context for <b>{principal}</b>"
    elif step == "memory_write":
        entry = esc(detail.get("entry", ""))[:300]
        body = (f"wrote summary back to the memory bank under <b>{esc(detail.get('principal'))}</b>"
                f"<div class='recall'>{entry}…</div>")
    elif step == "tool_call":
        args = ", ".join(f"{esc(k)}={esc(v)}" for k, v in (detail.get("args") or {}).items())
        body = f"called <code>{esc(detail.get('tool'))}</code>({args}) <span class='chip ok'>ok</span>"
    elif step.endswith("_result"):
        result = esc((detail.get("result") or ""))[:300]
        body = (f"task {esc(detail.get('task_id') or '')} done — "
                f"<div class='recall'>{result}…</div>")
    else:  # incident_accepted / incident_resolved / task_* bookkeeping
        bits = ", ".join(f"{esc(k)}={esc(v)[:80]}" for k, v in detail.items() if k != "raw")
        body = esc(bits or step)

    cls = "row blocked" if blocked else ("row memory" if step in MEMORY_STEPS else "row")
    return (f"<div class='{cls}'><span class='t'>{esc(_time(span.get('ts', '')))}</span>"
            f"<span class='a'>{esc(span['agent'])}</span>"
            f"<span class='s'>{esc(step)}</span>"
            f"<span class='m'>llm: {esc(model_id)}</span>"
            f"<div class='b'>{body}</div></div>")


def render_dashboard(session: dict | None, spans: list[dict], model_id: str) -> str:
    n_block = sum(1 for s in spans if s["step"] in BLOCK_STEPS or s.get("status") == "error")
    iid = (session or {}).get("incident_id", spans[0]["incident_id"] if spans else "-")
    status = (session or {}).get("status", "pre-incident decisions" if iid == "-" else "")
    svc = esc((session or {}).get("service", ""))

    rows = "".join(_row(s, model_id) for s in spans) or \
        "<div class='row'><span class='t'></span><span class='a'>—</span>" \
        "<div class='b'>no spans recorded — incident unknown?</div></div>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FleetOps trace — {esc(iid)}</title>
<style>
 body{{font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
      margin:0;background:#fafafa;color:#202124}}
 .wrap{{max-width:1080px;margin:0 auto;padding:24px 20px 64px}}
 h1{{font-size:20px;margin:0 0 4px}}
 .meta{{color:#5f6368;margin-bottom:16px}}
 .model-line{{background:#e8f0fe;border-left:4px solid #1a73e8;padding:8px 12px;
      border-radius:4px;margin-bottom:18px;font-size:13px}}
 .row{{display:grid;grid-template-columns:96px 100px 150px 110px 1fr;gap:10px;
      padding:7px 10px;border-bottom:1px solid #ececec;background:#fff;align-items:baseline}}
 .row.blocked{{background:#fdecec;border-left:4px solid #c5221f}}
 .row.memory{{border-left:3px solid #8ab4f8}}
 .t{{color:#5f6368;font-variant-numeric:tabular-nums;white-space:nowrap}}
 .a{{font-weight:600;white-space:nowrap}}
 .s{{color:#1a73e8;font-size:12.5px;word-break:break-all}}
 .row.blocked .s{{color:#c5221f;font-weight:600}}
 .m{{color:#9aa0a6;font-size:11.5px;white-space:nowrap}}
 .b{{grid-column:5;min-width:0}}
 .recall{{background:#f8f9fa;border-radius:4px;padding:6px 10px;margin-top:4px;
      color:#3c4043;font-size:12.5px;white-space:pre-wrap}}
 .row.blocked .recall,.row.blocked b{{color:#a50e0e}}
 code{{background:#f1f3f4;padding:1px 5px;border-radius:3px;font-size:12px}}
 .chip{{display:inline-block;margin-left:6px;padding:0 8px;border-radius:10px;
      font-size:11.5px;font-weight:600}}
 .chip.ok{{background:#e6f4ea;color:#137333}}
 .chip.deny{{background:#fce8e6;color:#a50e0e}}
 footer{{margin-top:24px;color:#9aa0a6;font-size:12px}}
</style></head><body><div class="wrap">
<h1>Incident {esc(iid)} <span class="chip {'deny' if status in ('blocked',) else 'ok'}">{esc(status)}</span></h1>
<div class="meta">service: {svc or '—'} · {len(spans)} spans · {n_block} rejected/blocked</div>
<div class="model-line"><b>Mandatory-stack compliance:</b> active model id recorded as a span
attribute on every hop — <code>{esc(model_id)}</code></div>
{rows}
<footer>FleetOps observability dashboard (Stage 2c) · spans emitted via the OpenTelemetry SDK,
persisted to Firestore <code>traces</code> · JSON: <a href="/traces?incident_id={esc(iid)}">/traces?incident_id={esc(iid)}</a></footer>
</div></body></html>"""
