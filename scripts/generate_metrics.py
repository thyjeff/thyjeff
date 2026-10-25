#!/usr/bin/env python3
"""
thyjeff // profile card
Generates a minimal GitHub-page-style SVG card (dark + light) from live data.
Browser chrome + tab row + avatar + intro + quiet stats + tech tiles + sparkline.
Runs locally and inside .github/workflows/metrics.yml — stdlib only.

Outputs:
  assets/dashboard.svg        (dark)
  assets/dashboard/dashboard-light.svg -> assets/dashboard-light.svg (light)
  assets/data.json            (last-known-good cache / fallback)
  assets/avatar.b64           (cached avatar data-uri fallback)
"""

import base64
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


# ---------------------------------------------------------------- data layer

def api(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "metrics-generator"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_avatar():
    """Return a data: URI of the user's avatar, cached to disk for fallback."""
    cache_path = os.path.join(ASSETS, "avatar.b64")
    try:
        req = urllib.request.Request(
            f"https://avatars.githubusercontent.com/{USER}?s=232",
            headers={"User-Agent": "metrics-generator"})
        with urllib.request.urlopen(req, timeout=30) as r:
            b64 = base64.b64encode(r.read()).decode()
        with open(cache_path, "w") as f:
            f.write(b64)
        return "data:image/png;base64," + b64
    except Exception as e:
        print("avatar fetch failed:", e)
        try:
            with open(cache_path) as f:
                return "data:image/png;base64," + f.read().strip()
        except Exception:
            return None


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
        data.update(
            name=u.get("name") or USER,
            repos_public=u["public_repos"],
            since=u["created_at"][:10],
        )
    except Exception as e:
        print("user fetch failed:", e)
        data.update({k: cache.get(k) for k in ("name", "repos_public", "since")})

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
    try:
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
    page="#0d1117", chrome="#161b22", chrome_text="#8b949e", pill="#010409",
    tab_active="#e6edf3", tab_inactive="#8b949e", accent="#f78166",
    card="#0d1117", border="#30363d", stats_bg="#161b22",
    text="#e6edf3", dim="#8b949e", faint="#6e7681",
    blue="#4493f8", green="#3fb950", tile="#161b22",
)
LIGHT = dict(
    page="#ffffff", chrome="#24292e", chrome_text="#ffffff", pill="#32383f",
    tab_active="#24292f", tab_inactive="#57606a", accent="#f9826c",
    card="#ffffff", border="#d0d7de", stats_bg="#f6f8fa",
    text="#24292f", dim="#57606a", faint="#8c959f",
    blue="#0969da", green="#1a7f37", tile="#ffffff",
)

CSS = """
text { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; }
.mono { font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; }
.dim { fill: %dim%; } .faint { fill: %faint%; } .t { fill: %text%; }
@keyframes led { 0%,100% { opacity: 1; } 50% { opacity: .3; } }
.led { animation: led 2.4s infinite; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def render(d, p, avatar=None):
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    s = []

    # ---------- quiet stats
    window = (today - dt.timedelta(days=i) for i in range(168))
    scores = [d["days"].get(x.isoformat(), 0) for x in window]
    contributions = sum(scores)
    active_days = len([x for x in scores if x > 0])
    since = d.get("since", "2024-09-26")
    since_lbl = dt.date.fromisoformat(since).strftime("%b %Y")

    # ---------- 14-day sparkline
    spark = [d["days"].get((today - dt.timedelta(days=i)).isoformat(), 0)
             for i in range(13, -1, -1)]
    sx0, sx1, sy0, sy1 = 792, 1120, 492, 556
    smax = max(4, max(spark))
    pts = []
    for i, v in enumerate(spark):
        px = sx0 + (sx1 - sx0) * i / 13
        py = sy1 - (sy1 - sy0) * (v / smax)
        pts.append(f"{px:.0f},{py:.0f}")

    # ---------- document
    css = CSS
    for k, v in p.items():
        css = css.replace(f"%{k}%", v)
    s.append('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="660" '
             'viewBox="0 0 1200 660" role="img" aria-label="thyjeff — GitHub-style profile card">')
    s.append("<title>thyjeff // profile card</title>")
    s.append(f"<style>{css}</style>")
    s.append(f'<rect width="1200" height="660" fill="{p["page"]}"/>')

    # ---------- browser chrome
    s.append(f'<path d="M0 10 a10 10 0 0 1 10-10 h1180 a10 10 0 0 1 10 10 v28 h-1200 z" '
             f'fill="{p["chrome"]}"/>')
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        s.append(f'<circle cx="{28 + i * 22}" cy="14" r="5" fill="{c}"/>')
    s.append(f'<rect x="430" y="4" width="340" height="22" rx="11" fill="{p["pill"]}"/>')
    s.append(f'<text x="600" y="19" font-size="11" text-anchor="middle" '
             f'fill="{p["chrome_text"]}" class="mono">github.com/{USER} · auto-refresh</text>')

    # ---------- tab row
    ty = 60
    s.append(f'<text x="64" y="{ty}" font-size="13.5" font-weight="600" '
             f'fill="{p["tab_active"]}">Overview</text>')
    s.append(f'<rect x="64" y="{ty + 9}" width="60" height="2.5" rx="1" fill="{p["accent"]}"/>')
    tabs = [(150, f"Repositories", d.get("repos_public", 0)), (280, "Projects", None),
            (380, "Packages", None)]
    for x, label, count in tabs:
        s.append(f'<text x="{x}" y="{ty}" font-size="13.5" fill="{p["tab_inactive"]}">'
                 f'{label}{"  " if count is not None else ""}'
                 f'<tspan class="faint">{count if count is not None else ""}</tspan></text>')
    s.append(f'<circle cx="1108" cy="{ty - 4}" r="4" fill="{p["green"]}" class="led"/>')
    s.append(f'<text x="1118" y="{ty}" font-size="11.5" fill="{p["tab_inactive"]}">live</text>')
    s.append(f'<line x1="0" y1="82" x2="1200" y2="82" stroke="{p["border"]}"/>')

    # ---------- body card
    s.append(f'<rect x="48" y="104" width="1104" height="532" rx="6" fill="{p["card"]}" '
             f'stroke="{p["border"]}"/>')

    # avatar (left rail)
    s.append(f'<clipPath id="avc"><circle cx="166" cy="240" r="62"/></clipPath>')
    if avatar:
        s.append(f'<image x="104" y="178" width="124" height="124" clip-path="url(#avc)" '
                 f'href="{avatar}"/>')
    else:
        s.append(f'<circle cx="166" cy="240" r="62" fill="{p["stats_bg"]}" '
                 f'stroke="{p["border"]}"/>')
        s.append(f'<text x="166" y="262" font-size="44" font-weight="600" text-anchor="middle" '
                 f'fill="{p["dim"]}">J</text>')
    s.append(f'<circle cx="166" cy="240" r="62" fill="none" stroke="{p["border"]}"/>')
    s.append(f'<text x="166" y="332" font-size="13" text-anchor="middle" class="dim">'
             f'@{USER}</text>')

    # intro
    name = d.get("name") or "Jefflin Immanuel"
    s.append(f'<text x="290" y="206" font-size="25" font-weight="600" fill="{p["text"]}">'
             f'&#128075; Hi, I&#8217;m {esc(name)}</text>')
    s.append(f'<text x="290" y="236" font-size="14" class="dim">deep learning · computer '
             f'vision · robotics · networking · embedded systems</text>')
    s.append(f'<line x1="290" y1="262" x2="1130" y2="262" stroke="{p["border"]}"/>')

    # bullets (left column)
    bullets = [
        ("&#127793;", "training deep learning models that see and act"),
        ("&#128064;", "computer vision focus — cameras in the loop"),
        ("&#128225;", "networking &amp; WiFi automation"),
        ("&#128296;", "Raspberry Pi 5 + dev boards on the edge"),
        ("&#128233;", f"say hi — LinkedIn · X @{USER}_"),
    ]
    by = 296
    for icon, textline in bullets:
        s.append(f'<text x="290" y="{by}" font-size="13.5" fill="{p["text"]}">'
                 f'<tspan>{icon}</tspan>  {textline}</text>')
        by += 31

    # stats card (right column) — quiet stats only, no follower/star counts
    s.append(f'<rect x="790" y="282" width="340" height="158" rx="6" fill="{p["stats_bg"]}" '
             f'stroke="{p["border"]}"/>')
    s.append(f'<text x="806" y="306" font-size="12.5" font-weight="600" fill="{p["blue"]}">'
             f'&#128202; GitHub Statistics</text>')
    rows = [
        ("contributions · 24 wks", contributions),
        ("active days", active_days),
        ("public repos", d.get("repos_public", 0)),
        ("member since", since_lbl),
    ]
    ry = 330
    for label, val in rows:
        s.append(f'<text x="806" y="{ry}" font-size="12.5" class="dim">{label}</text>')
        s.append(f'<text x="1114" y="{ry}" font-size="12.5" font-weight="600" '
                 f'text-anchor="end" fill="{p["text"]}">{esc(val)}</text>')
        ry += 26

    # tech tiles
    s.append(f'<rect x="290" y="458" width="4" height="18" rx="1" fill="{p["border"]}"/>')
    s.append(f'<text x="304" y="472" font-size="15" font-weight="600" fill="{p["text"]}">'
             f'&#128295; tech</text>')
    tiles = ["Python", "PyTorch", "OpenCV", "Isaac Lab", "ROS 2",
             "Linux", "Docker", "Pi 5", "Kotlin", "JavaScript"]
    for i, tile in enumerate(tiles):
        tx = 290 + (i % 5) * 152
        tyy = 488 + (i // 5) * 46
        s.append(f'<rect x="{tx}" y="{tyy}" width="140" height="36" rx="6" fill="{p["tile"]}" '
                 f'stroke="{p["border"]}"/>')
        s.append(f'<text x="{tx + 70}" y="{tyy + 23}" font-size="12.5" text-anchor="middle" '
                 f'class="dim">{tile}</text>')

    # activity sparkline (right column, under stats)
    s.append(f'<rect x="790" y="458" width="4" height="18" rx="1" fill="{p["border"]}"/>')
    s.append(f'<text x="804" y="472" font-size="15" font-weight="600" fill="{p["text"]}">'
             f'&#128200; activity · 14d</text>')
    s.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{p["green"]}" '
             f'stroke-width="1.8" stroke-linejoin="round"/>')
    for i in (0, 13):
        px = sx0 + (sx1 - sx0) * i / 13
        py = sy1 - (sy1 - sy0) * (spark[i] / smax)
        s.append(f'<circle cx="{px:.0f}" cy="{py:.0f}" r="2.6" fill="{p["green"]}"/>')
    s.append(f'<text x="{sx0}" y="572" font-size="10.5" class="faint">-14d</text>')
    s.append(f'<text x="{sx1}" y="572" font-size="10.5" text-anchor="end" class="faint">now</text>')

    # footer
    s.append(f'<text x="1130" y="620" font-size="10.5" text-anchor="end" class="faint">'
             f'auto-generated daily · github actions · {esc(now.strftime("%Y-%m-%d"))}</text>')

    s.append("</svg>")
    return "\n".join(s)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    data = collect()
    data["avatar_uri"] = fetch_avatar() or ""
    with open(os.path.join(ASSETS, "data.json"), "w") as f:
        json.dump({k: v for k, v in data.items() if k != "avatar_uri"}, f, indent=1, sort_keys=True)
    avatar = data["avatar_uri"] or None
    for name, pal in (("dashboard.svg", DARK), ("dashboard-light.svg", LIGHT)):
        svg = render(data, pal, avatar=avatar)
        with open(os.path.join(ASSETS, name), "w") as f:
            f.write(svg)
        print(f"wrote assets/{name} ({len(svg) // 1024} KB)")
    print("snapshot:", {"repos_public": data.get("repos_public"), "since": data.get("since")})


if __name__ == "__main__":
    main()
