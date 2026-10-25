#!/usr/bin/env python3
"""
thyjeff // console
Generates a minimal animated SVG dashboard (dark + light) from live GitHub data.
Hero: 3D isometric contribution calendar (GitHub-green). Accent: tiny neural net.
Runs locally and inside .github/workflows/metrics.yml — stdlib only.

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

WEEKS = 24
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
        repos = api(f"/users/{USER}/repos?per_page=100")
        own = [r for r in repos if not r["fork"]]
        data.update(
            repos_public=u["public_repos"],
            since=u["created_at"][:10],
        )
    except Exception as e:
        print("user/repos fetch failed:", e)
        data["repos_public"] = cache.get("repos_public", 0)
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
    try:
        for page in (1, 2, 3):
            for e in api(f"/users/{USER}/events/public?per_page=100&page={page}"):
                d = e["created_at"][:10]
                if e["type"] == "PushEvent":
                    days[d] = days.get(d, 0) + max(1, e.get("payload", {}).get("size", 1))
                elif e["type"] in ("CreateEvent", "PublicEvent", "PullRequestEvent",
                                   "IssuesEvent", "ReleaseEvent", "ForkEvent"):
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
    return data


# ---------------------------------------------------------------- svg render

DARK = dict(
    bg="#0d1117", panel="#161b22", stroke="#30363d",
    text="#e6edf3", dim="#8b949e", faint="#6e7681",
    green="#3fb950", good="#3fb950",
    tile="#e6edf3", tile_stroke="#afb8c1",
)
LIGHT = dict(
    bg="#f6f8fa", panel="#ffffff", stroke="#d0d7de",
    text="#1f2328", dim="#656d76", faint="#8c959f",
    green="#1a7f37", good="#1a7f37",
    tile="#ffffff", tile_stroke="#d0d7de",
)
# GitHub contribution greens, level 1..4 (top face); side faces get shaded.
LEVELS = ["#9be9a8", "#40c463", "#30a14e", "#216e39"]
LANG_COLORS = ["#9be9a8", "#40c463", "#30a14e", "#216e39", "#39d353", "#6e7681"]

CSS = """
text { font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace; }
.dim { fill: %dim%; } .faint { fill: %faint%; } .t { fill: %text%; }
@keyframes led { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
.led  { animation: led 2.2s infinite; }
.led2 { animation: led 2.2s .7s infinite; }
.led3 { animation: led 2.2s 1.4s infinite; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def shade(hexcolor, f):
    """Multiply a #rrggbb color by factor f."""
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(
        min(255, int(r * f)), min(255, int(g * f)), min(255, int(b * f)))


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
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    s = []

    langs = sorted(d["langs"].items(), key=lambda x: -x[1])
    ltotal = sum(n for _, n in langs) or 1
    top = langs[:5]

    # ---------- calendar data (WEEKS columns, 7 weekday rows, Mon-start)
    first_day = today - dt.timedelta(days=DAYS - 1)
    first_monday = first_day - dt.timedelta(days=first_day.weekday())
    cols = []
    for c in range(WEEKS):
        week = []
        for r in range(7):
            day = first_monday + dt.timedelta(days=c * 7 + r)
            week.append((day, d["days"].get(day.isoformat(), 0)))
        cols.append(week)

    scores = [score for week in cols for (_, score) in week if score > 0]
    total = sum(scores)
    highest = max(scores) if scores else 0
    streak = best = 0
    for week in cols:
        for (_, score) in week:
            streak = streak + 1 if score > 0 else 0
            best = max(best, streak)
    avg = total / DAYS

    # ---------- svg head
    css = CSS
    for k, v in p.items():
        css = css.replace(f"%{k}%", v)
    s.append('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="680" '
             'viewBox="0 0 1200 680" role="img" aria-label="thyjeff console — isometric '
             'contribution calendar and live GitHub metrics">')
    s.append("<title>thyjeff // console</title>")
    s.append(f"<style>{css}</style>")
    s.append(f'<rect width="1200" height="680" fill="{p["bg"]}"/>')

    # ---------- header
    s.append(f'<text x="28" y="40" font-size="19" font-weight="700" fill="{p["green"]}">'
             f'&#9648; thyjeff <tspan fill="{p["dim"]}" font-weight="400">// console</tspan></text>')
    s.append(f'<circle cx="1080" cy="35" r="4" fill="{p["good"]}" class="led"/>')
    s.append(f'<text x="1092" y="39" font-size="10" class="dim">live</text>')
    s.append(f'<text x="1172" y="39" font-size="9" text-anchor="end" class="faint">'
             f'ckpt {esc(now.strftime("%Y%m%d.%H%M"))}Z</text>')
    s.append(f'<line x1="24" y1="58" x2="1176" y2="58" stroke="{p["stroke"]}"/>')

    # ---------- hero: isometric calendar
    s.append(f'<rect x="24" y="74" width="1152" height="360" rx="10" fill="{p["panel"]}" '
             f'stroke="{p["stroke"]}"/>')

    ox, oy = 190, 134
    w2, h2 = 23, 9.5
    heights = [0, 8, 15, 22, 29]

    # month labels along the top edge (first week of each month)
    for c in range(WEEKS):
        day0 = cols[c][0][0]
        if c == 0 or day0.month != cols[c - 1][0][0].month:
            mx, my = ox + c * w2, oy + c * h2 - 26
            s.append(f'<text x="{mx:.0f}" y="{my:.0f}" font-size="9" text-anchor="middle" '
                     f'class="faint">{day0.strftime("%b").upper()}</text>')

    # tiles + blocks, painter-ordered back → front
    today_xy = None
    for depth in range(WEEKS + 6):
        for c in range(WEEKS):
            r = depth - c
            if not 0 <= r <= 6:
                continue
            day, score = cols[c][r]
            cx = ox + (c - r) * w2
            cy = oy + (c + r) * h2
            lv = level(score)
            H = heights[lv]
            if day == today:
                today_xy = (cx, cy, H)
            base = LEVELS[lv - 1] if lv else None
            if H == 0:
                s.append(f'<polygon points="{cx},{cy - h2} {cx + w2},{cy} {cx},{cy + h2} '
                         f'{cx - w2},{cy}" fill="{p["tile"]}" stroke="{p["tile_stroke"]}" '
                         f'stroke-width="0.6"/>')
            else:
                fc_top = base
                fc_right = shade(base, 0.80)
                fc_left = shade(base, 0.58)
                s.append(f'<polygon points="{cx - w2},{cy - H} {cx},{cy + h2 - H} {cx},{cy + h2} '
                         f'{cx - w2},{cy}" fill="{fc_left}"/>')
                s.append(f'<polygon points="{cx + w2},{cy - H} {cx},{cy + h2 - H} {cx},{cy + h2} '
                         f'{cx + w2},{cy}" fill="{fc_right}"/>')
                s.append(f'<polygon points="{cx},{cy - h2 - H} {cx + w2},{cy - H} {cx},{cy + h2 - H} '
                         f'{cx - w2},{cy - H}" fill="{fc_top}"/>')

    # pulse ring on today's tile
    if today_xy:
        cx, cy, H = today_xy
        s.append(f'<polygon points="{cx},{cy - h2 - H} {cx + w2},{cy - H} {cx},{cy + h2 - H} '
                 f'{cx - w2},{cy - H}" fill="none" stroke="{p["good"]}" stroke-width="1.6">'
                 f'<animate attributeName="opacity" values="1;0.15;1" dur="1.8s" '
                 f'repeatCount="indefinite"/></polygon>')

    # stats column (right side of hero)
    sx = 800
    s.append(f'<text x="{sx}" y="120" font-size="10" letter-spacing="2" class="dim" '
             f'font-weight="600">CONTRIBUTIONS <tspan fill="{p["green"]}">// {WEEKS} WKS</tspan></text>')
    s.append(f'<text x="{sx}" y="170" font-size="42" font-weight="700" fill="{p["green"]}">{total}</text>')
    s.append(f'<text x="{sx}" y="192" font-size="9" class="faint">push events · public signal</text>')
    rows = [("best streak", f"{best}d"), ("highest / day", str(highest)),
            ("average / day", f"{avg:.1f}"), ("public repos", str(d.get("repos_public", 0)))]
    ry = 232
    for label, val in rows:
        s.append(f'<text x="{sx}" y="{ry}" font-size="10" class="dim">{label}</text>')
        s.append(f'<text x="1160" y="{ry}" font-size="10" text-anchor="end" '
                 f'fill="{p["text"]}">{esc(val)}</text>')
        ry += 24
    # legend: flat tile + 4 green levels
    ly = 400
    lx = sx
    s.append(f'<text x="{lx}" y="{ly}" font-size="8" class="faint">less</text>')
    lx += 26
    tiles = [p["tile"]] + LEVELS
    for col in tiles:
        s.append(f'<polygon points="{lx},{ly - 8} {lx + 8},{ly - 4} {lx},{ly} {lx - 8},{ly - 4}" '
                 f'fill="{col}" stroke="{p["tile_stroke"]}" stroke-width="0.5"/>')
        lx += 22
    s.append(f'<text x="{lx + 2}" y="{ly - 2}" font-size="8" class="faint">more</text>')

    # ---------- bottom left: languages
    s.append(f'<rect x="24" y="450" width="640" height="136" rx="10" fill="{p["panel"]}" '
             f'stroke="{p["stroke"]}"/>')
    s.append(f'<text x="40" y="476" font-size="10" letter-spacing="2" class="dim" '
             f'font-weight="600">LANGUAGES</text>')
    bx, by, bw, bh = 40, 492, 608, 16
    s.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" fill="{shade(p["panel"], 0.92) if not light else "#eaeef2"}" '
             f'stroke="{p["stroke"]}" stroke-width="0.6"/>')
    seg_x = bx
    for i, (name, n) in enumerate(top):
        w = max(2.0, bw * n / ltotal)
        s.append(f'<rect x="{seg_x:.1f}" y="{by + 1.5}" width="{w:.1f}" height="{bh - 3}" '
                 f'fill="{LANG_COLORS[i]}" opacity="0.95"/>')
        seg_x += w
    lx = bx
    for i, (name, n) in enumerate(top):
        pct = round(100 * n / ltotal)
        if pct < 1:
            continue
        label = f"{name} {pct}%"
        s.append(f'<circle cx="{lx + 3:.1f}" cy="534" r="3" fill="{LANG_COLORS[i]}"/>')
        s.append(f'<text x="{lx + 10:.1f}" y="537" font-size="9" class="dim">{esc(label)}</text>')
        lx += 10 + len(label) * 5.4 + 16

    # ---------- bottom right: minimal neural accent (no labels)
    s.append(f'<rect x="684" y="450" width="492" height="136" rx="10" fill="{p["panel"]}" '
             f'stroke="{p["stroke"]}"/>')
    inp = [(724, 486), (724, 518), (724, 550)]
    hid = [(930, 470), (930, 502), (930, 534), (930, 566)]
    outp = [(1132, 494), (1132, 542)]
    net_edges = []
    for (x1, y1) in inp:
        for (x2, y2) in hid:
            net_edges.append((x1 + 7, y1, x2 - 6, y2))
    for (x1, y1) in hid:
        for (x2, y2) in outp:
            net_edges.append((x1 + 6, y1, x2 - 8, y2))
    for i, (x1, y1, x2, y2) in enumerate(net_edges):
        s.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{p["stroke"]}" '
                 f'stroke-width="0.8"/>')
    for (x, y) in inp:
        s.append(f'<circle cx="{x}" cy="{y}" r="7" fill="{p["bg"]}" stroke="{p["green"]}" stroke-width="1.4"/>')
    for (x, y) in hid:
        s.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{p["bg"]}" stroke="{p["dim"]}" stroke-width="1.1"/>')
    for (x, y) in outp:
        s.append(f'<circle cx="{x}" cy="{y}" r="8" fill="{p["bg"]}" stroke="{p["green"]}" stroke-width="1.4"/>')
    for i, idx in enumerate([0, 6, 9, 14, 17, 20, 24, 26]):
        if idx >= len(net_edges):
            continue
        x1, y1, x2, y2 = net_edges[idx]
        eid = f"n{idx}"
        s.append(f'<path id="{eid}" d="M{x1} {y1} L{x2} {y2}" fill="none"/>')
        s.append(f'<circle r="2.2" fill="{p["green"]}">'
                 f'<animateMotion dur="{1.6 + (i % 4) * 0.5:.2f}s" begin="{(i * 0.45) % 2.2:.2f}s" '
                 f'repeatCount="indefinite"><mpath href="#{eid}"/></animateMotion></circle>')

    # ---------- footer: edge fleet chips + regen note
    chips = [("RPI-5", "led"), ("DEV BOARDS", "led2"), ("WIFI · AUTOLOGIN", "led3")]
    fx = 30
    for name, led in chips:
        s.append(f'<circle cx="{fx}" cy="612" r="4" fill="{p["good"]}" class="{led}"/>')
        s.append(f'<text x="{fx + 12}" y="616" font-size="9.5" class="dim">{name}</text>')
        fx += 12 + len(name) * 5.8 + 26
    s.append(f'<text x="1172" y="616" font-size="8.5" text-anchor="end" class="faint">'
             f'auto-regen · github actions · 03:37 utc</text>')

    s.append("</svg>")
    return "\n".join(s)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    data = collect()
    with open(os.path.join(ASSETS, "data.json"), "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    for name, pal, light in (("dashboard.svg", DARK, False),
                             ("dashboard-light.svg", LIGHT, True)):
        svg = render(data, pal, light=light)
        with open(os.path.join(ASSETS, name), "w") as f:
            f.write(svg)
        print(f"wrote assets/{name} ({len(svg) // 1024} KB)")
    print("snapshot:", {"repos_public": data.get("repos_public"), "since": data.get("since")})


if __name__ == "__main__":
    main()
