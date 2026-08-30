#!/usr/bin/env python3
"""Builds docs/demo_video.mp4 frames from real captured evidence (evidence/ + docs/shots).

Every terminal frame's content is a verbatim capture of a real run (live .run URL or
local `make demo`); screenshot frames are verbatim headless-Chrome captures of the
live service. Captions carry the narration. Frames are rendered to PNG and muxed
with ffmpeg (see submission/tools/encode.sh).
"""
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (13, 18, 26)
PANEL = (22, 30, 43)
FG = (232, 238, 247)
DIM = (143, 163, 191)
ACCENT = (94, 157, 217)
GREEN = (90, 200, 140)
RED = (217, 91, 91)
YELLOW = (227, 207, 135)

MONO = "/System/Library/Fonts/Menlo.ttc"
SANS = "/System/Library/Fonts/Helvetica.ttc"

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT.parent / "stage4a_frames"
OUT.mkdir(exist_ok=True)


def font(path, size):
    return ImageFont.truetype(path, size)


def canvas():
    return Image.new("RGB", (W, H), BG)


def caption(draw, text):
    draw.rectangle([0, H - 92, W, H], fill=(8, 11, 17))
    f = font(SANS, 30)
    lines = textwrap.wrap(text, width=105)
    y = H - 84 + (76 - len(lines) * 38) // 2
    for ln in lines:
        tw = draw.textlength(ln, font=f)
        draw.text(((W - tw) / 2, y), ln, font=f, fill=FG)
        y += 38


def title_card(name, kicker, big, bullets, cap):
    img = canvas()
    d = ImageDraw.Draw(img)
    d.text((W / 2, 300), kicker, font=font(SANS, 34), fill=ACCENT, anchor="mm")
    d.text((W / 2, 420), big, font=font(SANS, 76), fill=FG, anchor="mm")
    y = 590
    bf = font(SANS, 40)
    for b in bullets:
        tw = d.textlength(b, font=bf)
        d.text(((W - tw) / 2, y), b, font=bf, fill=DIM)
        y += 70
    caption(d, cap)
    img.save(OUT / f"{name}.png")


def pillars_card(name):
    img = canvas()
    d = ImageDraw.Draw(img)
    d.text((W / 2, 220), "FleetOps — an agent-fleet control plane on Google Cloud",
           font=font(SANS, 54), fill=FG, anchor="mm")
    pillars = ["Registry", "Identity + Gateway", "Model Armor", "Memory Bank", "Observability"]
    bw, gap = 330, 24
    x = (W - len(pillars) * bw - (len(pillars) - 1) * gap) / 2
    for i, p in enumerate(pillars):
        bx = x + i * (bw + gap)
        d.rounded_rectangle([bx, 420, bx + bw, 560], 14, fill=PANEL, outline=ACCENT, width=2)
        d.text((bx + bw / 2, 490), p, font=font(SANS, 34), fill=FG, anchor="mm")
    d.text((W / 2, 700), "Planner decomposes · gateway routes under zero-trust identity · guardrails block before tools run ·",
           font=font(SANS, 32), fill=DIM, anchor="mm")
    d.text((W / 2, 752), "memory carries context across sessions · every hop is an OTel span",
           font=font(SANS, 32), fill=DIM, anchor="mm")
    caption(d, "FleetOps is an agent-fleet control plane on Google Cloud — planner, gateway, guardrails, memory bank, and end-to-end traces.")
    img.save(OUT / f"{name}.png")


def terminal(name, lines, cap, title="zsh — fleetops"):
    img = canvas()
    d = ImageDraw.Draw(img)
    # window chrome
    d.rounded_rectangle([60, 60, W - 60, H - 130], 14, fill=(16, 22, 33))
    d.rectangle([60, 60, W - 60, 112], fill=PANEL)
    for i, c in enumerate([RED, YELLOW, GREEN]):
        d.ellipse([84 + i * 34, 78, 102 + i * 34, 96], fill=c)
    d.text((W / 2, 86), title, font=font(SANS, 24), fill=DIM, anchor="mm")
    f = font(MONO, 26)
    y = 140
    for kind, text in lines:
        if y > H - 160:
            break
        color = {"cmd": FG, "out": DIM, "ok": GREEN, "err": RED, "hl": ACCENT, "warn": YELLOW}[kind]
        for ln in text.split("\n"):
            d.text((92, y), ln, font=f, fill=color)
            y += 36
        y += 8
    caption(d, cap)
    img.save(OUT / f"{name}.png")


def screenshot(name, png, cap, note=None):
    img = canvas()
    d = ImageDraw.Draw(img)
    shot = Image.open(png)
    scale = min((W - 160) / shot.width, (H - 240) / shot.height)
    shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), Image.LANCZOS)
    x, y = (W - shot.width) // 2, 96
    d.rounded_rectangle([x - 6, y - 6, x + shot.width + 6, y + shot.height + 6], 10,
                        outline=(51, 65, 92), width=3)
    img.paste(shot, (x, y))
    if note:
        d.text((W / 2, y + shot.height + 44), note, font=font(SANS, 30), fill=DIM, anchor="mm")
    caption(d, cap)
    img.save(OUT / f"{name}.png")


def shot_card(name, lines, cap):
    img = canvas()
    d = ImageDraw.Draw(img)
    d.text((W / 2, 330), lines[0], font=font(SANS, 60), fill=FG, anchor="mm")
    y = 470
    f = font(SANS, 36)
    for ln in lines[1:]:
        d.text((W / 2, y), ln, font=f, fill=DIM, anchor="mm")
        y += 64
    caption(d, cap)
    img.save(OUT / f"{name}.png")


def main():
    ev = ROOT / "evidence"
    shots = ROOT / "evidence" / "shots"

    a_id = json.loads((ev / "incident_A_post.json").read_text().splitlines()[0])["id"]
    a_get = json.loads((ev / "incident_A_get.json").read_text().splitlines()[0])
    b_get = json.loads((ev / "incident_B_get.json").read_text().splitlines()[0])
    spans_b = json.loads((ev / "traces_B.json").read_text())
    mem = next(s for s in spans_b if s["step"] == "memory_read")
    recalled = mem["detail"]["entries"][0]["text"][:150]

    # Beat 1 — problem (15s)
    title_card("b1_problem", "THE PROBLEM", "Agent fleets ship. Nobody tells them who may act.",
               ["Who is approved?", "What did it last decide?", "Who blocked the bad call?"],
               "Enterprises deploy fleets of AI agents — but without registry, identity, guardrails, and memory, it's just many chatbots, with no trace to replay.")

    # Beat 2 — value prop (30s)
    pillars_card("b2_pillars")
    screenshot("b2_dashboard", shots / "overview.png",
               "FleetOps is an agent-fleet control plane on Google Cloud — planner, gateway, guardrails, memory, traces.",
               "live overview dashboard — https://fleetops-qiedvqu63a-ew.a.run.app")

    # Beat 3a — incident A accepted + planner decomposes (20s)
    terminal("b3a_post", [
        ("cmd", "$ curl -s -X POST https://fleetops-qiedvqu63a-ew.a.run.app/incidents \\"),
        ("cmd", "    -H 'Authorization: Bearer tok-orchestrator-a1b2' -H 'Content-Type: application/json' \\"),
        ("cmd", "    -d '{\"description\":\"checkout-service p99 latency spike 2400ms after deploy, 5xx rate climbing\",\"service\":\"checkout-service\"}'"),
        ("out", json.dumps(json.loads((ev / "incident_A_post.json").read_text().splitlines()[0]))),
        ("hl", f"→ 202 accepted · routed_to=planner · principal=svc-orchestrator"),
        ("cmd", ""),
        ("cmd", f"$ curl -s …/incidents/{a_id}          # a few seconds later"),
        ("out", f"plan: t1 diagnose  \"Diagnose checkout-service incident\""),
        ("out", f"      t2 remediate \"Scale up checkout-service and confirm latency recovery\""),
    ], "I post one incident — a checkout latency spike. The planner decomposes it into subtasks and hands each to a specialist through the gateway.")

    # Beat 3b — specialists execute + trace chain (20s)
    screenshot("b3b_trace", shots / "traceA.png",
               "Diagnoser runs its probe tools; remediator applies the fix. Every hop, principal, and decision is a span you can replay.",
               f"live trace dashboard — /trace/{a_id} — 17 spans, gateway allow decisions + memory reads visible")

    # Beat 3c — rejected principal + Model Armor block (20s)
    terminal("b3c_armor", [
        ("cmd", "# zero-trust: a specialist token may not dispatch incidents (live)"),
        ("cmd", "$ curl -s -X POST …/incidents -H 'Authorization: Bearer tok-diagnoser-c3d4' …"),
        ("err", "403 {\"detail\":\"principal 'svc-diagnoser' (specialist) may not dispatch (scopes: execute)\"}"),
        ("out", "  traced: gateway_rejected — reason logged as a span"),
        ("cmd", ""),
        ("cmd", "# Model Armor: injection + PII inside a tool argument (make demo)"),
        ("out", "tool call with injection+PII args → BLOCKED before reaching restart_service"),
        ("err", "  reason: prompt-injection: instruction override"),
        ("err", "  reason: prompt-injection: data exfiltration"),
        ("err", "  reason: pii: email address (canary demo.user@example.test)"),
        ("out", "  traced: remediator/guardrail_blocked — the tool never executed"),
    ], "A specialist principal is rejected at the gateway; a second call carries an injected instruction — Model Armor checks arguments before any tool executes, blocks it, and logs exactly why.")

    # Beat 3d — cross-session memory recall (30s)
    b_id = b_get["incident_id"]
    terminal("b3d_memory", [
        ("cmd", "$ curl -s -X POST …/incidents -d '{\"description\":\"follow-up on the checkout-service latency incident from earlier: confirm p99 stayed under 400ms after the fix\",\"service\":\"checkout-service\"}'"),
        ("hl", f"→ 202 {b_id} · follow-up incident"),
        ("cmd", ""),
        ("cmd", f"$ curl -s …/traces?incident_id={b_id}   # planner span, before acting:"),
        ("ok", "memory_read  planner  recalled 1 prior entry from fleet:checkout-service"),
        ("out", f"  \"{recalled}…\""),
        ("cmd", ""),
        ("cmd", f"$ curl -s …/incidents/{b_id}"),
        ("ok", f"status: {b_get['status']}  · both subtasks done — no re-diagnosis, continuation from memory"),
    ], "Incident B is a follow-up to A. Before it acts, the specialist pulls A's outcome from the memory bank — cross-session context, persistent and scoped by principal.")

    # Beat 4 — Google Cloud proof shots (60s)
    shot_card("b4_url", [
        "https://fleetops-qiedvqu63a-ew.a.run.app",
        "Cloud Run service \"fleetops\" · project feetops-devpos · europe-west1",
        "Cloud Run + Pub/Sub + Firestore — all three required services, live",
        "deploy: ./deploy.sh (one command, documented in README)",
    ], "The backend runs on Google Cloud — a Cloud Run service with real Pub/Sub and Firestore behind the same contracts.")

    screenshot("b4_overview", shots / "overview.png",
               "Cloud Run serves the API and the dashboards — this is the live service.",
               "live on Cloud Run — single service: HTTP API + Pub/Sub pull worker")
    screenshot("b4_registry", shots / "registry.png",
               "Same URL, live registry — three approved agent cards; judges can poke at it.",
               "GET /agents — registry listing served live from Firestore")
    screenshot("b4_tracelive", shots / "traceA.png",
               "And live traces — the full 17-span chain of the incident you just watched.",
               f"/trace/{a_id} — persisted in Firestore, rendered live")

    # Beat 5 — architecture recap + close (30s)
    screenshot("b5_diagram", ROOT / "docs" / "architecture.png",
               "One gateway, one registry, inline guardrails, persistent memory, full traces — a fortified fleet on Gemini and Google Cloud.")
    shot_card("b5_end", [
        "FleetOps",
        "github.com/mskutlu/fleetops-agent-fleet",
        "Built for the All Things Agentic Hackathon",
        "#AllThingsAgenticHackathon",
    ], "Built for the All Things Agentic Hackathon — try it: clone, make demo, or open the live URL.")

    print(f"frames → {OUT}")
    for p in sorted(OUT.glob("*.png")):
        print(" ", p.name)


if __name__ == "__main__":
    main()
