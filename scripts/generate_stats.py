#!/usr/bin/env python3
"""Generate contribution-graph and stats SVGs from real GitHub data.

Uses only the Python standard library. Reads:
  GH_TOKEN  - token for the GraphQL API (required)
  GH_USER   - username (defaults to the repo owner)
Writes SVGs into ./assets (light + dark variants).
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "allenasat044-prog"
TOKEN = os.environ.get("GH_TOKEN")
OUT = os.path.join(os.path.dirname(__file__), "..", "assets")

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    name
    login
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount contributionLevel weekday }
        }
      }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100, after: $after) {
      totalCount
      nodes { stargazerCount }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

THEMES = {
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "title": "#1f2328", "text": "#656d76",
        "num": "#0969da",
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "title": "#e6edf3", "text": "#8b949e",
        "num": "#58a6ff",
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
}
LEVEL_INDEX = {
    "NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4,
}
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"


def gql(variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json",
                 "User-Agent": "profile-stats-action"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "errors" in data:
        sys.exit(f"GraphQL error: {data['errors']}")
    return data["data"]["user"]


def fetch():
    user = gql({"login": USER, "after": None})
    stars = sum(n["stargazerCount"] for n in user["repositories"]["nodes"])
    page = user["repositories"]["pageInfo"]
    while page["hasNextPage"]:
        more = gql({"login": USER, "after": page["endCursor"]})["repositories"]
        stars += sum(n["stargazerCount"] for n in more["nodes"])
        page = more["pageInfo"]
    return user, stars


def streaks(days):
    days = sorted(days, key=lambda d: d["date"])
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    # current streak: today may still be empty, so skip it
    current = 0
    idx = len(days) - 1
    if idx >= 0 and days[idx]["contributionCount"] == 0:
        idx -= 1
    while idx >= 0 and days[idx]["contributionCount"] > 0:
        current += 1
        idx -= 1
    return current, longest


def graph_svg(weeks, total, t):
    cell, gap = 11, 3
    step = cell + gap
    left, top = 40, 56
    width = left + len(weeks) * step + 22
    height = top + 7 * step + 46
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
         f'viewBox="0 0 {width} {height}" font-family="{FONT}">',
         f'<rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="10" '
         f'fill="{t["bg"]}" stroke="{t["border"]}"/>',
         f'<text x="22" y="30" font-size="15" font-weight="600" fill="{t["title"]}">'
         f'{total:,} contributions in the last year</text>']

    # day labels (Mon / Wed / Fri)
    for wd, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        p.append(f'<text x="{left-8}" y="{top + wd*step + 9}" font-size="9" '
                 f'text-anchor="end" fill="{t["text"]}">{label}</text>')

    last_month, last_x = None, -99
    for wi, week in enumerate(weeks):
        x = left + wi * step
        days = week["contributionDays"]
        if days:
            month = dt.date.fromisoformat(days[0]["date"]).strftime("%b")
            if month != last_month and x - last_x >= 30:
                p.append(f'<text x="{x}" y="{top-8}" font-size="10" '
                         f'fill="{t["text"]}">{month}</text>')
                last_month, last_x = month, x
        for d in days:
            lvl = LEVEL_INDEX.get(d["contributionLevel"], 0)
            n = d["contributionCount"]
            tip = f'{n} contribution{"s" if n != 1 else ""} on {d["date"]}'
            p.append(f'<rect x="{x}" y="{top + d["weekday"]*step}" width="{cell}" '
                     f'height="{cell}" rx="2" fill="{t["levels"][lvl]}">'
                     f'<title>{escape(tip)}</title></rect>')

    # legend
    ly = top + 7 * step + 18
    lx = width - 22 - (5 * step) - 60
    p.append(f'<text x="{lx}" y="{ly+9}" font-size="10" text-anchor="end" '
             f'fill="{t["text"]}">Less</text>')
    for i, c in enumerate(t["levels"]):
        p.append(f'<rect x="{lx + 6 + i*step}" y="{ly}" width="{cell}" height="{cell}" '
                 f'rx="2" fill="{c}"/>')
    p.append(f'<text x="{lx + 12 + 5*step}" y="{ly+9}" font-size="10" '
             f'fill="{t["text"]}">More</text>')
    p.append("</svg>")
    return "\n".join(p)


def stats_svg(name, items, t, width):
    height = 150
    col = (width - 40) / len(items)
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
         f'viewBox="0 0 {width} {height}" font-family="{FONT}">',
         f'<rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="10" '
         f'fill="{t["bg"]}" stroke="{t["border"]}"/>',
         f'<text x="22" y="34" font-size="16" font-weight="600" fill="{t["title"]}">'
         f'{escape(name)}\'s GitHub Stats</text>']
    for i, (label, value) in enumerate(items):
        cx = 20 + col * i + col / 2
        p.append(f'<text x="{cx:.1f}" y="88" font-size="28" font-weight="700" '
                 f'text-anchor="middle" fill="{t["num"]}">{escape(str(value))}</text>')
        p.append(f'<text x="{cx:.1f}" y="112" font-size="12" text-anchor="middle" '
                 f'fill="{t["text"]}">{escape(label)}</text>')
    p.append("</svg>")
    return "\n".join(p)


def main():
    if not TOKEN:
        sys.exit("GH_TOKEN is not set")
    user, stars = fetch()
    cc = user["contributionsCollection"]
    cal = cc["contributionCalendar"]
    weeks = cal["weeks"]
    all_days = [d for w in weeks for d in w["contributionDays"]]
    current, longest = streaks(all_days)

    items = [
        ("Contributions (1y)", f'{cal["totalContributions"]:,}'),
        ("Current streak", f"{current}d"),
        ("Longest streak", f"{longest}d"),
        ("Stars earned", f"{stars:,}"),
        ("Repositories", f'{user["repositories"]["totalCount"]:,}'),
        ("Pull requests", f'{user["pullRequests"]["totalCount"]:,}'),
    ]
    name = user["name"] or user["login"]

    os.makedirs(OUT, exist_ok=True)
    for theme, t in THEMES.items():
        g = graph_svg(weeks, cal["totalContributions"], t)
        gw = int(g.split('width="')[1].split('"')[0])
        with open(os.path.join(OUT, f"contributions-{theme}.svg"), "w", encoding="utf-8") as f:
            f.write(g)
        with open(os.path.join(OUT, f"stats-{theme}.svg"), "w", encoding="utf-8") as f:
            f.write(stats_svg(name, items, t, gw))
    print(f"OK: {cal['totalContributions']} contributions, streak {current}/{longest}")


if __name__ == "__main__":
    main()
