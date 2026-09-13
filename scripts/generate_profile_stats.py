#!/usr/bin/env python3
"""Generate profile README cards from all public owned repositories.

Includes both original repos and forks. Uses only the Python standard library
so the weekly Action stays short. Language share is GitHub Linguist byte
volume, not commit count.
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_GRAPHQL = "https://api.github.com/graphql"
USERNAME = os.environ.get("PROFILE_USERNAME", "AsagiriBeta")
OUT_DIR = Path(__file__).resolve().parent.parent / "assets"

BG = "#071018"
CARD = "#0b1a24"
BORDER = "#1c3d4a"
TEXT = "#e7f3f0"
MUTED = "#8ba4b4"
MIST = "#5eead4"
SKY = "#93c5fd"
VIOLET = "#c4b5fd"
OTHER_COLOR = "#64748b"
FONT = "ui-sans-serif, Segoe UI, Helvetica Neue, Arial, sans-serif"


def require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.stderr.write("GITHUB_TOKEN or GH_TOKEN is required\n")
        sys.exit(1)
    return token


def graphql(token: str, query: str, variables: dict | None = None) -> dict:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    request = urllib.request.Request(
        GITHUB_GRAPHQL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "asagiri-profile-stats",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"GitHub GraphQL HTTP {error.code}: {detail}") from error
    if body.get("errors"):
        raise SystemExit(f"GitHub GraphQL errors: {body['errors']}")
    return body["data"]


def fetch_public_repos(token: str, username: str) -> list[dict]:
    query = """
    query ($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(
          ownerAffiliations: OWNER
          privacy: PUBLIC
          first: 100
          after: $cursor
        ) {
          pageInfo { hasNextPage endCursor }
          nodes {
            name
            isFork
            stargazerCount
            forkCount
            languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name color } }
            }
          }
        }
      }
    }
    """
    repos: list[dict] = []
    cursor = None
    while True:
        data = graphql(token, query, {"login": username, "cursor": cursor})
        connection = data["user"]["repositories"]
        repos.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
    return repos


def aggregate(repos: list[dict]) -> dict:
    languages: dict[str, dict] = {}
    stars = 0
    fork_repos = 0
    coded_repos = 0
    for repo in repos:
        stars += repo.get("stargazerCount") or 0
        if repo.get("isFork"):
            fork_repos += 1
        edges = repo.get("languages", {}).get("edges") or []
        if edges:
            coded_repos += 1
        for edge in edges:
            node = edge["node"]
            name = node["name"]
            entry = languages.setdefault(
                name, {"bytes": 0, "color": node.get("color") or OTHER_COLOR}
            )
            entry["bytes"] += edge["size"]
            if node.get("color"):
                entry["color"] = node["color"]
    total_bytes = sum(item["bytes"] for item in languages.values())
    ranked = sorted(languages.items(), key=lambda item: item[1]["bytes"], reverse=True)
    return {
        "repo_count": len(repos),
        "original_count": len(repos) - fork_repos,
        "fork_count": fork_repos,
        "coded_repos": coded_repos,
        "stars": stars,
        "total_bytes": total_bytes,
        "ranked": ranked,
    }


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_bytes(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


def polar(cx: float, cy: float, radius: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return cx + radius * math.cos(rad), cy + radius * math.sin(rad)


def donut_slice(
    cx: float, cy: float, outer: float, inner: float, start: float, end: float
) -> str:
    span = end - start
    if span <= 0.08:
        return ""
    if span >= 359.92:
        return (
            f"M {cx + outer:.2f} {cy:.2f} "
            f"A {outer:.2f} {outer:.2f} 0 1 1 {cx - outer:.2f} {cy:.2f} "
            f"A {outer:.2f} {outer:.2f} 0 1 1 {cx + outer:.2f} {cy:.2f} "
            f"M {cx + inner:.2f} {cy:.2f} "
            f"A {inner:.2f} {inner:.2f} 0 1 0 {cx - inner:.2f} {cy:.2f} "
            f"A {inner:.2f} {inner:.2f} 0 1 0 {cx + inner:.2f} {cy:.2f} Z"
        )
    large = 1 if span > 180 else 0
    p0 = polar(cx, cy, outer, start)
    p1 = polar(cx, cy, outer, end)
    q1 = polar(cx, cy, inner, end)
    q0 = polar(cx, cy, inner, start)
    return (
        f"M {p0[0]:.2f} {p0[1]:.2f} "
        f"A {outer:.2f} {outer:.2f} 0 {large} 1 {p1[0]:.2f} {p1[1]:.2f} "
        f"L {q1[0]:.2f} {q1[1]:.2f} "
        f"A {inner:.2f} {inner:.2f} 0 {large} 0 {q0[0]:.2f} {q0[1]:.2f} Z"
    )


def slice_rows(ranked: list[tuple[str, dict]], total_bytes: int, limit: int = 6) -> list[dict]:
    if total_bytes <= 0:
        return []
    top = ranked[:limit]
    rest = ranked[limit:]
    rows = []
    for name, meta in top:
        rows.append(
            {
                "name": name,
                "bytes": meta["bytes"],
                "color": meta["color"],
                "share": meta["bytes"] / total_bytes,
            }
        )
    other_bytes = sum(meta["bytes"] for _, meta in rest)
    if other_bytes:
        rows.append(
            {
                "name": "Other",
                "bytes": other_bytes,
                "color": OTHER_COLOR,
                "share": other_bytes / total_bytes,
            }
        )
    return rows


def card_shell(
    width: int, height: int, title: str, subtitle: str, body: str, gradient_id: str
) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{xml_escape(title)}">
  <defs>
    <linearGradient id="{gradient_id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{BG}"/>
      <stop offset="100%" stop-color="{CARD}"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="url(#{gradient_id})" stroke="{BORDER}" stroke-width="1.2"/>
  <circle cx="{width - 36}" cy="28" r="54" fill="{MIST}" opacity="0.05"/>
  <text x="28" y="38" fill="{MIST}" font-family="{FONT}" font-size="11" font-weight="600" letter-spacing="1.6">ASAGIRI</text>
  <text x="28" y="64" fill="{TEXT}" font-family="{FONT}" font-size="20" font-weight="700">{xml_escape(title)}</text>
  <text x="28" y="86" fill="{MUTED}" font-family="{FONT}" font-size="12">{xml_escape(subtitle)}</text>
  {body}
</svg>
'''


def render_overview(stats: dict) -> str:
    metrics = [
        (str(stats["repo_count"]), "Public repositories"),
        (f"{stats['original_count']} / {stats['fork_count']}", "Originals / forks"),
        (str(len(stats["ranked"])), "Languages"),
        (format_bytes(stats["total_bytes"]), "Linguist volume"),
    ]
    boxes = []
    for index, (value, label) in enumerate(metrics):
        col, row = index % 2, index // 2
        x = 28 + col * 188
        y = 112 + row * 78
        boxes.append(
            f'''<g>
  <rect x="{x}" y="{y}" width="176" height="66" rx="12" fill="#06141c" stroke="{BORDER}"/>
  <text x="{x + 16}" y="{y + 30}" fill="{TEXT}" font-family="{FONT}" font-size="22" font-weight="700">{xml_escape(value)}</text>
  <text x="{x + 16}" y="{y + 50}" fill="{MUTED}" font-family="{FONT}" font-size="11">{xml_escape(label)}</text>
</g>'''
        )
    body = "\n  ".join(boxes)
    return card_shell(
        420,
        280,
        "Public snapshot",
        "All public repositories, including forks",
        body,
        "overview-bg",
    )


def render_languages(stats: dict) -> str:
    rows = slice_rows(stats["ranked"], stats["total_bytes"])
    cx, cy, outer, inner = 108, 188, 78, 48
    paths = []
    cursor = -90.0
    for row in rows:
        span = row["share"] * 360.0
        d = donut_slice(cx, cy, outer, inner, cursor, cursor + span)
        cursor += span
        if d:
            paths.append(
                f'<path d="{d}" fill="{row["color"]}" stroke="{BG}" stroke-width="1.4"/>'
            )
    top_name = rows[0]["name"] if rows else "—"
    top_pct = f"{rows[0]['share'] * 100:.0f}%" if rows else "0%"
    legend = []
    for index, row in enumerate(rows):
        y = 118 + index * 22
        bar_width = max(4, round(row["share"] * 148))
        legend.append(
            f'''<g>
  <rect x="208" y="{y - 9}" width="8" height="8" rx="2" fill="{row["color"]}"/>
  <text x="224" y="{y}" fill="{TEXT}" font-family="{FONT}" font-size="12">{xml_escape(row["name"])}</text>
  <text x="392" y="{y}" fill="{MUTED}" font-family="{FONT}" font-size="12" text-anchor="end">{row["share"] * 100:.1f}%</text>
  <rect x="208" y="{y + 6}" width="184" height="3" rx="1.5" fill="#10222c"/>
  <rect x="208" y="{y + 6}" width="{bar_width}" height="3" rx="1.5" fill="{row["color"]}"/>
</g>'''
        )
    body = f'''<g>
  {"".join(paths)}
  <text x="{cx}" y="{cy - 4}" text-anchor="middle" fill="{TEXT}" font-family="{FONT}" font-size="16" font-weight="700">{xml_escape(top_pct)}</text>
  <text x="{cx}" y="{cy + 14}" text-anchor="middle" fill="{MUTED}" font-family="{FONT}" font-size="10">{xml_escape(top_name)}</text>
  {"".join(legend)}
</g>'''
    return card_shell(
        420,
        280,
        "Language share",
        "Public originals and forks · by code volume",
        body,
        "languages-bg",
    )


def write_svg(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.rstrip() + "\n"
    path.write_text(normalized, encoding="utf-8")


def main() -> int:
    token = require_token()
    repos = fetch_public_repos(token, USERNAME)
    stats = aggregate(repos)
    write_svg(OUT_DIR / "overview.svg", render_overview(stats))
    write_svg(OUT_DIR / "languages.svg", render_languages(stats))
    print(
        f"Wrote cards for {stats['repo_count']} public repos "
        f"({stats['original_count']} original, {stats['fork_count']} forks), "
        f"{len(stats['ranked'])} languages, {format_bytes(stats['total_bytes'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
