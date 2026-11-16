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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "yoshida"
skills.ICON_DIR = PROJECT / "assets" / "icons"
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
    all_repos = skills.gather(cfg)

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
                "featured": bool(item.get("featured", False)),
                "lang": lang,
                "lang_color": LANG_COLORS.get(lang, DEFAULT_LANG_COLOR),
                "version": latest["tag_name"] if latest else "no release",
                "stage": ("beta" if latest and latest.get("prerelease") else "stable")
                if latest
                else "wip",
            }
        )
    other = [r for r in all_repos if r.source != "github" and not r.fork]
    stars += sum(r.stars for r in other)
    stats = [
        {"label": "repos", "value": str(len(repos) + len(other))},
        {"label": "stars", "value": str(stars)},
        {"label": "releases", "value": str(releases)},
        {"label": "yrs coding", "value": str(years_since(cfg["coding_since"], today))},
    ]
    main, sub = skills.compute(all_repos, cfg, today)
    return {"stats": stats, "projects": projects, "skills": {"main": main, "sub": sub}}


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
        "cards": [
            {**c, "id": f"{c['id']}-{m}", "mode": m}
            for c in data["projects"]
            for m in ("dark", "light")
        ],
    }
    (PROJECT / "cards" / "hero.cards.json").write_text(
        json.dumps(hero, indent=2) + "\n"
    )
    (PROJECT / "cards" / "projects.cards.json").write_text(
        json.dumps(projects, indent=2) + "\n"
    )
    skills_cards = {
        "format": 1,
        "design": "designs/skills.design.json",
        "cards": [{"id": f"skills-{m}", "mode": m, **data["skills"]} for m in ("dark", "light")],
    }
    (PROJECT / "cards" / "skills.cards.json").write_text(
        json.dumps(skills_cards, indent=2) + "\n"
    )
    # Intro and footer are text cards, one per colour theme.
    version = (PROJECT / "YOSHIDA_VERSION").read_text().strip()
    notes = {
        "intro": (cfg.get("intro", ""), "designs/intro.design.json"),
        "footer": (f"cards drawn with Yoshida {version}, rebuilt daily, nya~", "designs/footer.design.json"),
    }
    for name, (text, design) in notes.items():
        cards = [{"id": f"{name}-{m}", "mode": m, "text": text} for m in ("dark", "light")]
        (PROJECT / "cards" / f"{name}.cards.json").write_text(
            json.dumps({"format": 1, "design": design, "cards": cards}, indent=2) + "\n"
        )
    # Write the files in Yoshida's canonical layout, so diffs only show real changes.
    yoshida(
        "fmt",
        str(PROJECT / "cards" / "intro.cards.json"),
        str(PROJECT / "cards" / "footer.cards.json"),
        str(PROJECT / "cards" / "hero.cards.json"),
        str(PROJECT / "cards" / "projects.cards.json"),
        str(PROJECT / "cards" / "skills.cards.json"),
    )


def yoshida(*args: str) -> None:
    exe = os.environ.get("YOSHIDA_BIN") or shutil.which("yoshida")
    if not exe:
        raise SystemExit("yoshida binary not found: set YOSHIDA_BIN or put it on PATH")
    subprocess.run([exe, *args], check=True)


def read_existing() -> dict:
    hero = json.loads((PROJECT / "cards" / "hero.cards.json").read_text())
    projects = json.loads((PROJECT / "cards" / "projects.cards.json").read_text())
    dark = []
    for c in projects["cards"]:
        if c.get("mode") == "dark":
            c = {k: v for k, v in c.items() if k != "mode"}
            c["id"] = c["id"].removesuffix("-dark")
            dark.append(c)
    projects = {"cards": dark}
    skill_card = json.loads((PROJECT / "cards" / "skills.cards.json").read_text())["cards"][0]
    return {
        "stats": hero["cards"][0]["stats"],
        "projects": projects["cards"],
        "skills": {"main": skill_card["main"], "sub": skill_card["sub"]},
    }


def render(out: Path, now: dt.datetime) -> None:
    from PIL import Image  # imported late so --help works without Pillow

    work = out / ".work"
    shutil.rmtree(work, ignore_errors=True)
    # Fixed clock: the cards do not print the time, and a pinned instant keeps output reproducible.
    clock = ["--now", "2026-01-01T00:00:00Z"]
    try:
        yoshida("fmt", "--check", str(PROJECT))
    except subprocess.CalledProcessError:
        raise SystemExit(
            "Some files in yoshida/ are not in Yoshida's layout. "
            "Run `yoshida fmt yoshida` (or enable .githooks/pre-commit) and commit."
        )
    yoshida("check", str(PROJECT))
    # The hero is rendered at 2x and kept at 2x, so it stays sharp on high-dpi screens.
    yoshida("render", str(PROJECT), "--set", "hero", "--scale", "2", "--out", str(work / "png"), *clock)
    yoshida("render", str(PROJECT), "--set", "projects", "--svg", "--out", str(work / "svg"), *clock)
    # Icons inside the skills card are pixels in an SVG, so give them a high resolution.
    yoshida("render", str(PROJECT), "--set", "skills", "--svg", "--scale", "4", "--out", str(work / "svg"), *clock)
    # Contact chips carry a brand icon, so they get the same high resolution.
    yoshida("render", str(PROJECT), "--set", "contacts", "--svg", "--scale", "4", "--out", str(work / "svg"), *clock)
    yoshida("render", str(PROJECT), "--set", "headings", "--svg", "--out", str(work / "svg"), *clock)
    yoshida("render", str(PROJECT), "--set", "intro", "--svg", "--out", str(work / "svg"), *clock)
    # The footer prints the render date, so it is the only set that uses the real clock.
    stamp = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    yoshida("render", str(PROJECT), "--set", "footer", "--svg", "--out", str(work / "svg"), "--now", stamp)

    frames = [
        Image.open(work / "png" / "hero" / f"f{i:02d}.png").convert("RGB")
        for i in range(FRAMES)
    ]
    # One palette for all frames, taken from a strip of every frame, so colors do not jump.
    w, h = frames[0].size
    strip = Image.new("RGB", (w, h * FRAMES))
    for i, frame in enumerate(frames):
        strip.paste(frame, (0, i * h))
    palette = strip.quantize(256, method=Image.MEDIANCUT)
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
    (out / "skills.svg").unlink(missing_ok=True)
    for name in ("skills", "contacts", "headings", "intro", "footer"):
        shutil.rmtree(out / name, ignore_errors=True)
        shutil.copytree(work / "svg" / name, out / name)
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
    ap.add_argument("--now", help="pin the render time (YYYY-MM-DDTHH:MM:SSZ), for reproducible output")
    args = ap.parse_args()

    cfg = json.loads((PROJECT / "profile.config.json").read_text())
    data = read_existing() if args.offline else collect(cfg, dt.date.today())
    write_cards(cfg, data)
    now = (
        dt.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else dt.datetime.now(dt.timezone.utc)
    )
    render(Path(args.out), now)
    print(
        f"built {args.out}: hero.gif + {len(data['projects'])} project cards",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
