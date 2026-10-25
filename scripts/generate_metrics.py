#!/usr/bin/env python3
"""
thyjeff // embodied-ai console
Generates a self-animating SVG dashboard (dark + light) from live GitHub data.
Runs locally and inside .github/workflows/metrics.yml — stdlib only, no deps.

Outputs:
  assets/dashboard.svg        (dark)
  assets/dashboard-light.svg  (light)
  assets/data.json            (last-known-good cache / fallback)
"""

import datetime as dt
import html
import json
import os
import urllib.request

USER = os.environ.get("GH_USERNAME", "thyjeff")
TOKEN = os.environ.get("GITHUB_TOKEN")
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

WEEKS = 12
DAYS = WEEKS * 7


# ---------------------------------------------------------------- data layer

def api(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "metrics-generator"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def collect():
    """Pull everything; on partial failure fall back to the cached snapshot."""
    cache = {}
    try:
        with open(os.path.join(ASSETS, "data.json")) as f:
            cache = json.load(f)
    except Exception:
        pass

    data = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    try:
        u = api(f"/users/{USER}")
        repos = [r for r in api(f"/users/{USER}/repos?per_page=100") if not r["fork"]]
        data.update(
            repos_public=u["public_repos"],
            followers=u["followers"],
            stars=sum(r["stargazers_count"] for r in repos),
            since=u["created_at"][:10],
        )
    except Exception as e:
        print("user/repos fetch failed:", e)
        data.update({k: cache.get(k, 0) for k in ("repos_public", "followers", "stars")})
        data["since"] = cache.get("since", "2024-09-26")

    # languages (best effort, per repo)
    langs = {}
    try:
        for r in api(f"/users/{USER}/repos?per_page=100"):
            if r["fork"]:
                continue
            try:
                for lang, n in api(f"/repos/{USER}/{r['name']}/languages").items():
                    langs[lang] = langs.get(lang, 0) + n
            except Exception:
                pass
    except Exception as e:
        print("languages fetch failed:", e)
    data["langs"] = langs or cache.get("langs", {})

    # daily activity score over the trailing window
    days = {}
    today = dt.date.today()
    try:
        for page in (1, 2, 3):
            for e in api(f"/users/{USER}/events/public?per_page=100&page={page}"):
                d = e["created_at"][:10]
                if e["type"] == "PushEvent":
                    days[d] = days.get(d, 0) + max(1, e.get("payload", {}).get("size", 1))
                elif e["type"] in ("CreateEvent", "PublicEvent", "PullRequestEvent", "IssuesEvent", "ReleaseEvent"):
                    days[d] = days.get(d, 0) + 1
    except Exception as e:
        print("events fetch failed:", e)
    try:  # repo pushed_at days are a legit activity signal too
        for r in api(f"/users/{USER}/repos?per_page=100&sort=pushed"):
            d = r["pushed_at"][:10]
            days[d] = max(days.get(d, 0), 1)
    except Exception:
        pass
    if not days:
        days = cache.get("days", {})
    data["days"] = days
    data["active_days"] = len([d for d in days if (today - dt.date.fromisoformat(d)).days < DAYS])
    return data


# ---------------------------------------------------------------- svg render

DARK = dict(
    bg="#0b0f14", panel="#10161d", stroke="#1e2a36", grid="#16202a",
    text="#e6edf3", dim="#8b99a6", faint="#54626f",
    accent="#22d3ee", accent2="#a78bfa", accent3="#fbbf24", good="#34d399",
    empty="#1a2530",
)
LIGHT = dict(
    bg="#eef2f6", panel="#ffffff", stroke="#d5dde5", grid="#e2e8ee",
    text="#0f172a", dim="#5b6b7a", faint="#94a3b1",
    accent="#0891b2", accent2="#7c3aed", accent3="#b45309", good="#059669",
    empty="#dbe3ea",
)
LANG_COLORS = ["#22d3ee", "#a78bfa", "#fbbf24", "#34d399", "#f472b6", "#64748b"]
LANG_COLORS_L = ["#0891b2", "#7c3aed", "#b45309", "#059669", "#db2777", "#64748b"]

CSS = """
text { font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace; }
.t   { fill: %text%; }
.dim { fill: %dim%; }
.faint{ fill: %faint%; }
.acc { fill: %accent%; }
.h   { font-size: 11px; letter-spacing: 2px; font-weight: 600; }
@keyframes led { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
.led { animation: led 2.2s infinite; }
.led2 { animation: led 2.2s .7s infinite; }
.led3 { animation: led 2.2s 1.4s infinite; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def level(score):
    if score <= 0:
        return 0
    if score == 1:
        return 1
    if score <= 3:
        return 2
    if score <= 6:
        return 3
    return 4


def render(d, p, light=False):
    """p = palette dict. Returns full SVG string."""
    lang_colors = LANG_COLORS_L if light else LANG_COLORS
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    s = []

    # ---------- language mix
    langs = sorted(d["langs"].items(), key=lambda x: -x[1])
    total = sum(n for _, n in langs) or 1
    top, other = langs[:5], sum(n for _, n in langs[5:])

    # ---------- network geometry (panel 1)
    inp = [(88, 170, "V", "VISION"), (88, 268, "L", "LANGUAGE"), (88, 366, "S", "STATE")]
    h1 = [(225, y) for y in (130, 218, 306, 394)]
    h2 = [(330, y) for y in (130, 218, 306, 394)]
    out = [(425, 170, "\u0394x"), (425, 268, "\u0394\u03b8"), (425, 366, "grip")]

    edges = []
    eid = 0
    edge_ids = []
    for (x1, y1, *_) in inp:
        for (x2, y2) in h1:
            eid += 1
            edges.append((f"e{eid}", x1 + 14, y1, x2 - 12, y2))
            edge_ids.append(f"e{eid}")
    for (x1, y1) in h1:
        for (x2, y2) in h2:
            eid += 1
            edges.append((f"e{eid}", x1 + 12, y1, x2 - 12, y2))
            edge_ids.append(f"e{eid}")
    for (x1, y1) in h2:
        for (x2, y2, *_) in out:
            eid += 1
            edges.append((f"e{eid}", x1 + 12, y1, x2 - 13, y2))
            edge_ids.append(f"e{eid}")
    # pulses: a spread of travelling activations across the graph
    pulse_edges = ["e1", "e9", "e13", "e18", "e22", "e28", "e31", "e35", "e40", "e44",
                   "e46", "e49", "e52", "e55", "e58"]
    pulse_colors = [p["accent"], p["accent2"], p["accent3"]]

    # ---------- reward grid geometry (panel 3)
    gx, gy = 540, 264
    cw, ch = 7.35, 13.2
    grid = []
    for col in range(DAYS):
        day = today - dt.timedelta(days=DAYS - 1 - col)
        score = d["days"].get(day.isoformat(), 0)
        grid.append((day, score, gx + col * cw, gy + (day.weekday()) * ch))

    last_active = max(
        (g for g in grid if g[1] > 0), key=lambda g: g[0], default=None
    )

    # ---------- stat chips (panel 2)
    years = (dt.date.fromisoformat(d.get("since", "2024-09-26")) and
             (today - dt.date.fromisoformat(d.get("since", "2024-09-26"))).days / 365.25)
    chips = [
        ("PUBLIC REPOS", d.get("repos_public", 0), "code under version control"),
        ("STARS EARNED", d.get("stars", 0), "across all repos"),
        ("FOLLOWERS", d.get("followers", 0), "signal listeners"),
        ("ONLINE FOR", f"{years:.1f}y".replace(".0y", "y"), f"since {d.get('since','?')[:7]}"),
    ]
    chip_xs = [540, 699, 858, 1017]

    # ---------- svg head
    css = CSS
    for k, v in p.items():
        css = css.replace(f"%{k}%", v)

    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="640" '
             f'viewBox="0 0 1200 640" role="img" aria-label="thyjeff embodied-AI console — live GitHub metrics">')
    s.append(f"<title>thyjeff // embodied-ai console</title>")
    s.append(f"<style>{css}</style>")
    s.append(f'<defs>'
             f'<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">'
             f'<circle cx="1" cy="1" r="1" fill="{p["grid"]}"/></pattern>'
             f'<linearGradient id="scan" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="{p["accent"]}" stop-opacity="0"/>'
             f'<stop offset=".5" stop-color="{p["accent"]}" stop-opacity=".06"/>'
             f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0"/></linearGradient>'
             f'<linearGradient id="titlegrad" x1="0" y1="0" x2="1" y2="0">'
             f'<stop offset="0" stop-color="{p["accent"]}"/>'
             f'<stop offset="1" stop-color="{p["accent2"]}"/></linearGradient>'
             f'</defs>')

    s.append(f'<rect width="1200" height="640" rx="14" fill="{p["bg"]}"/>')
    s.append(f'<rect width="1200" height="640" rx="14" fill="url(#dots)"/>')

    # scanline sweep
    s.append(f'<rect width="1200" height="140" fill="url(#scan)">'
             f'<animateTransform attributeName="transform" type="translate" '
             f'from="0 -140" to="0 640" dur="9s" repeatCount="indefinite"/></rect>')

    # ---------- header
    s.append(f'<text x="28" y="42" font-size="19" font-weight="700" fill="url(#titlegrad)">'
             f'&#9648; thyjeff <tspan fill="{p["dim"]}" font-weight="400">// embodied-ai console</tspan></text>')
    s.append(f'<circle cx="938" cy="37" r="4" fill="{p["good"]}" class="led"/>')
    s.append(f'<text x="950" y="41" font-size="10" class="dim">sys:nominal</text>')
    s.append(f'<text x="1172" y="41" font-size="9" text-anchor="end" class="faint">'
             f'ckpt {esc(now.strftime("%Y%m%d.%H%M"))}Z</text>')
    s.append(f'<line x1="24" y1="62" x2="1176" y2="62" stroke="{p["stroke"]}"/>')

    # ---------- panel 1 : VLA policy network
    s.append(f'<rect x="24" y="88" width="476" height="384" rx="10" fill="{p["panel"]}" stroke="{p["stroke"]}"/>')
    s.append(f'<text x="40" y="112" class="h dim">VLA POLICY <tspan class="acc">// live inference</tspan></text>')

    for i, (ex, x1, y1, x2, y2) in enumerate(edges):
        s.append(f'<path id="{ex}" d="M{x1} {y1} L{x2} {y2}" stroke="{p["stroke"]}" '
                 f'stroke-width="1" fill="none"/>')
    for i, pe in enumerate(x for x in pulse_edges if x in edge_ids):
        ex, x1, y1, x2, y2 = next(e for e in edges if e[0] == pe)
        c = pulse_colors[i % 3]
        s.append(f'<circle r="2.6" fill="{c}">'
                 f'<animateMotion dur="{1.9 + (i % 4) * 0.45:.2f}s" begin="{(i * 0.37) % 2.4:.2f}s" '
                 f'repeatCount="indefinite"><mpath href="#{ex}"/></animateMotion></circle>')

    for (x, y, lab, cap) in inp:
        s.append(f'<circle cx="{x}" cy="{y}" r="14" fill="{p["bg"]}" stroke="{p["accent"]}" stroke-width="1.6"/>')
        s.append(f'<text x="{x}" y="{y + 4}" font-size="11" text-anchor="middle" class="acc" '
                 f'font-weight="700">{lab}</text>')
        s.append(f'<text x="{x}" y="{y + 30}" font-size="7.5" text-anchor="middle" class="faint">{cap}</text>')
    for (x, y) in h1 + h2:
        s.append(f'<circle cx="{x}" cy="{y}" r="12" fill="{p["bg"]}" stroke="{p["accent2"]}" stroke-width="1.2"/>')
    for (x, y, lab) in out:
        s.append(f'<circle cx="{x}" cy="{y}" r="13" fill="{p["bg"]}" stroke="{p["accent3"]}" stroke-width="1.6"/>')
        s.append(f'<text x="{x}" y="{y + 3}" font-size="7.5" text-anchor="middle" fill="{p["accent3"]}">{lab}</text>')
        s.append(f'<text x="{x}" y="{y + 30}" font-size="7.5" text-anchor="middle" class="faint">act</text>')

    s.append(f'<line x1="225" y1="122" x2="225" y2="402" stroke="{p["stroke"]}" stroke-dasharray="2 4"/>')
    s.append(f'<line x1="330" y1="122" x2="330" y2="402" stroke="{p["stroke"]}" stroke-dasharray="2 4"/>')
    s.append(f'<text x="277" y="428" font-size="8" text-anchor="middle" class="faint">'
             f'backbone \u00b7 transformer \u2014 cross-attn fusion</text>')
    s.append(f'<text x="40" y="448" font-size="8" class="faint">task: manipulation</text>')
    s.append(f'<text x="480" y="448" font-size="8" text-anchor="end" class="faint">sim: Isaac Lab</text>')
    s.append(f'<text x="40" y="462" font-size="8" class="faint">loop: 100 Hz</text>')
    s.append(f'<text x="480" y="462" font-size="8" text-anchor="end" class="faint">lat: 8.3 ms</text>')

    # ---------- panel 2 : telemetry chips
    s.append(f'<rect x="524" y="88" width="652" height="118" rx="10" fill="{p["panel"]}" stroke="{p["stroke"]}"/>')
    s.append(f'<text x="540" y="112" class="h dim">TELEMETRY <tspan class="acc">// github stream</tspan></text>')
    for (label, value, sub), x in zip(chips, chip_xs):
        s.append(f'<rect x="{x}" y="124" width="144" height="70" rx="8" fill="{p["bg"]}" stroke="{p["stroke"]}"/>')
        s.append(f'<text x="{x + 12}" y="142" font-size="8" letter-spacing="1.5" class="faint">{label}</text>')
        s.append(f'<text x="{x + 12}" y="168" font-size="21" font-weight="700" class="acc">{value}</text>')
        s.append(f'<text x="{x + 12}" y="184" font-size="7.5" class="faint">{esc(sub)}</text>')

    # ---------- panel 3 : reward grid
    s.append(f'<rect x="524" y="222" width="652" height="150" rx="10" fill="{p["panel"]}" stroke="{p["stroke"]}"/>')
    s.append(f'<text x="540" y="246" class="h dim">REWARD CURVE <tspan class="acc">// {WEEKS} wks of push signal</tspan></text>')
    s.append(f'<text x="1160" y="246" font-size="8" text-anchor="end" class="faint">'
             f'{d.get("active_days", 0)} active days</text>')
    op = [0, 0.4, 0.65, 0.85, 1.0]
    for (day, score, x, y) in grid:
        lv = level(score)
        if lv == 0:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.3" fill="{p["empty"]}"/>')
        else:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.9" fill="{p["accent"]}" '
                     f'opacity="{op[lv]}"/>')
    if last_active:
        lx, ly = last_active[2], last_active[3]
        s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="6.5" fill="none" stroke="{p["good"]}" '
                 f'stroke-width="1.4"><animate attributeName="r" values="4;9" dur="1.6s" '
                 f'repeatCount="indefinite"/><animate attributeName="opacity" values="1;0" '
                 f'dur="1.6s" repeatCount="indefinite"/></circle>')
    s.append(f'<text x="540" y="366" font-size="7.5" class="faint">{WEEKS} wks ago</text>')
    s.append(f'<text x="1160" y="366" font-size="7.5" text-anchor="end" class="faint">today</text>')

    # ---------- panel 4 : context mix (languages)
    s.append(f'<rect x="524" y="388" width="652" height="80" rx="10" fill="{p["panel"]}" stroke="{p["stroke"]}"/>')
    s.append(f'<text x="540" y="410" class="h dim">CONTEXT MIX <tspan class="acc">// language tokens</tspan></text>')
    bx, by, bw, bh = 540, 420, 620, 13
    s.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="6.5" fill="{p["empty"]}"/>')
    seg_x = bx
    segs = [(name, n / total, lang_colors[i]) for i, (name, n) in enumerate(top)]
    if other:
        segs.append(("other", other / total, lang_colors[5]))
    for name, frac, col in segs:
        w = max(2.0, bw * frac)
        s.append(f'<rect x="{seg_x:.1f}" y="{by + 1}" width="{w:.1f}" height="{bh - 2}" fill="{col}" opacity="0.9"/>')
        seg_x += w
    lx = bx
    for i, (name, n) in enumerate(top):
        pct = round(100 * n / total)
        if pct < 1:
            continue
        label = f"{name} {pct}%"
        s.append(f'<circle cx="{lx + 3:.1f}" cy="449" r="3" fill="{lang_colors[i]}"/>')
        s.append(f'<text x="{lx + 10:.1f}" y="452" font-size="8" class="dim">{esc(label)}</text>')
        lx += 10 + len(label) * 4.9 + 14

    # ---------- panel 5 : edge fleet
    s.append(f'<rect x="24" y="484" width="1152" height="88" rx="10" fill="{p["panel"]}" stroke="{p["stroke"]}"/>')
    s.append(f'<text x="40" y="508" class="h dim">EDGE FLEET <tspan class="acc">// deploy targets</tspan></text>')
    fleet = [
        ("RPI-5", "online", "led"),
        ("DEV-BOARDS", "online", "led2"),
        ("WIFI-NET", "ku-wl \u00b7 autologin", "led3"),
    ]
    fx = 40
    for name, status, led in fleet:
        wch = 26 + len(name) * 8 + len(status) * 5
        s.append(f'<rect x="{fx}" y="522" width="{wch}" height="32" rx="16" fill="{p["bg"]}" stroke="{p["stroke"]}"/>')
        s.append(f'<circle cx="{fx + 18}" cy="538" r="4" fill="{p["good"]}" class="{led}"/>')
        s.append(f'<text x="{fx + 30}" y="536" font-size="9.5" class="t" font-weight="600">{name}</text>')
        s.append(f'<text x="{fx + 30}" y="548" font-size="7" class="faint">{status}</text>')
        fx += wch + 14
    s.append(f'<text x="1160" y="540" font-size="8.5" text-anchor="end" class="dim">'
             f'deploy path: sim (Isaac Lab) \u2192 export \u2192 edge (Pi 5)</text>')

    # ---------- footer
    s.append(f'<text x="28" y="606" font-size="8" class="faint">'
             f'auto-regen: GitHub Actions \u00b7 daily 03:37 UTC \u00b7 on push</text>')
    s.append(f'<text x="1172" y="606" font-size="8" text-anchor="end" class="faint">'
             f'policy: curiosity-driven \u00b7 \u00a9 {now.year} thyjeff</text>')

    s.append("</svg>")
    return "\n".join(s)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    data = collect()
    with open(os.path.join(ASSETS, "data.json"), "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    for name, pal in (("dashboard.svg", DARK), ("dashboard-light.svg", LIGHT)):
        svg = render(data, pal, light=pal is LIGHT)
        with open(os.path.join(ASSETS, name), "w") as f:
            f.write(svg)
        print(f"wrote assets/{name} ({len(svg) // 1024} KB)")
    print("snapshot:", {k: data[k] for k in ("repos_public", "stars", "followers", "active_days")})


if __name__ == "__main__":
    main()
