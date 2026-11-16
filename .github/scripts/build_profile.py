#!/usr/bin/env python3
"""Build the profile cards: GitHub data -> Yoshida card files -> rendered images.

    python .github/scripts/build_profile.py [--out generated] [--offline]

--offline skips the GitHub API and reuses the values already in yoshida/cards.
Needs the Yoshida binary ($YOSHIDA_BIN or `yoshida` on PATH) and Pillow.
Only the standard library is used for the API calls.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "yoshida"
FRAMES = 12
FRAME_MS = 140

LANG_COLORS = {
    "Zig": "#EC915C",
    "Python": "#3572A5",
    "Rust": "#DEA584",
    "TypeScript": "#3178C6",
    "JavaScript": "#F1E05A",
    "C": "#555555",
    "C++": "#F34B7D",
    "Go": "#00ADD8",
    "Shell": "#89E051",
    "TeX": "#3D6117",
    "HTML": "#E34C26",
    "Java": "#B07219",
}
DEFAULT_LANG_COLOR = "#8CCBF5"


def api(path: str):
    """GET https://api.github.com<path>, parsed JSON. Uses GITHUB_TOKEN if set."""
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-build",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def years_since(date: str, today: dt.date) -> int:
    start = dt.date.fromisoformat(date)
    return max(0, int((today - start).days // 365.25))


def collect(cfg: dict, today: dt.date, fetch=api) -> dict:
    """Return {"stats": [...], "projects": [...]} from the GitHub API."""
    login = cfg["login"]
    repos = [
        r
        for r in fetch(f"/users/{login}/repos?per_page=100&type=owner")
        if not r["fork"]
    ]
    stars = sum(r["stargazers_count"] for r in repos)
    releases = 0
    for r in repos:
        releases += len(fetch(f"/repos/{login}/{r['name']}/releases?per_page=100"))
    by_name = {r["name"].lower(): r for r in repos}

    projects = []
    for item in cfg["featured"]:
        repo = by_name.get(item["repo"].lower())
        if repo is None:
            raise SystemExit(f"featured repo not found: {item['repo']}")
        latest = None
        try:
            latest = fetch(f"/repos/{login}/{repo['name']}/releases/latest")
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
        lang = repo.get("language") or "n/a"
        projects.append(
            {
                "id": repo["name"].lower(),
                "name": item.get("name", repo["name"]),
                "kind": item.get("kind", "oss"),
                "blurb": item.get("blurb") or repo.get("description") or "",
                "quip": item.get("quip", ""),
                "lang": lang,
                "lang_color": LANG_COLORS.get(lang, DEFAULT_LANG_COLOR),
                "version": latest["tag_name"] if latest else "no release",
                "stage": ("beta" if latest and latest.get("prerelease") else "stable")
                if latest
                else "wip",
            }
        )
    stats = [
        {"label": "repos", "value": str(len(repos))},
        {"label": "stars", "value": str(stars)},
        {"label": "releases", "value": str(releases)},
        {"label": "yrs coding", "value": str(years_since(cfg["coding_since"], today))},
    ]
    return {"stats": stats, "projects": projects}


def write_cards(cfg: dict, data: dict) -> None:
    hero = {
        "format": 1,
        "design": "designs/hero.design.json",
        "cards": [
            {
                "id": f"f{i:02d}",
                "f": i,
                "msg": cfg["hero_message"],
                "stats": data["stats"],
            }
            for i in range(FRAMES)
        ],
    }
    projects = {
        "format": 1,
        "design": "designs/project.design.json",
        "cards": data["projects"],
    }
    (PROJECT / "cards" / "hero.cards.json").write_text(
        json.dumps(hero, indent=2) + "\n"
    )
    (PROJECT / "cards" / "projects.cards.json").write_text(
        json.dumps(projects, indent=2) + "\n"
    )
    # Write the files in Yoshida's canonical layout, so diffs only show real changes.
    yoshida(
        "fmt",
        str(PROJECT / "cards" / "hero.cards.json"),
        str(PROJECT / "cards" / "projects.cards.json"),
    )


def yoshida(*args: str) -> None:
    exe = os.environ.get("YOSHIDA_BIN") or shutil.which("yoshida")
    if not exe:
        raise SystemExit("yoshida binary not found: set YOSHIDA_BIN or put it on PATH")
    subprocess.run([exe, *args], check=True)


def read_existing() -> dict:
    hero = json.loads((PROJECT / "cards" / "hero.cards.json").read_text())
    projects = json.loads((PROJECT / "cards" / "projects.cards.json").read_text())
    return {"stats": hero["cards"][0]["stats"], "projects": projects["cards"]}


def render(out: Path) -> None:
    from PIL import Image  # imported late so --help works without Pillow

    work = out / ".work"
    shutil.rmtree(work, ignore_errors=True)
    # Fixed clock: the cards do not print the time, and a pinned instant keeps output reproducible.
    clock = ["--now", "2026-01-01T00:00:00Z"]
    yoshida("fmt", "--check", str(PROJECT))
    yoshida("check", str(PROJECT))
    yoshida(
        "render",
        str(PROJECT),
        "--set",
        "hero",
        "--scale",
        "2",
        "--out",
        str(work / "png"),
        *clock,
    )
    yoshida(
        "render",
        str(PROJECT),
        "--set",
        "projects",
        "--svg",
        "--out",
        str(work / "svg"),
        *clock,
    )

    frames = [
        Image.open(work / "png" / "hero" / f"f{i:02d}.png")
        .convert("RGB")
        .resize((830, 260), Image.LANCZOS)
        for i in range(FRAMES)
    ]
    palette = frames[0].quantize(128, method=Image.MEDIANCUT)
    quant = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    out.mkdir(parents=True, exist_ok=True)
    quant[0].save(
        out / "hero.gif",
        save_all=True,
        append_images=quant[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=1,
    )
    dest = out / "projects"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(work / "svg" / "projects", dest)
    shutil.rmtree(work)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(ROOT / "generated"))
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    cfg = json.loads((PROJECT / "profile.config.json").read_text())
    data = read_existing() if args.offline else collect(cfg, dt.date.today())
    write_cards(cfg, data)
    render(Path(args.out))
    print(
        f"built {args.out}: hero.gif + {len(data['projects'])} project cards",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
