"""Work out main skills and sub skills from a person's repositories.

Sources are GitHub and Forgejo (Gitea) accounts. For every repository the
language bytes are weighted by how recently the repository was pushed and how
big it is, so a large, fresh project pushes its language up and an old one
slowly sinks. Topics can add skills that are not languages (Arduino, LaTeX, ...).

Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Language name -> skill name. Anything not listed keeps its own name.
RENAME = {"TeX": "LaTeX", "Shell": "Bash", "Dockerfile": "Docker"}

# Skill name -> file in yoshida/assets/icons (without .svg).
ICONS = {
    "Python": "python",
    "Git": "git",
    "Linux": "linux",
    "Arduino": "arduino",
    "Raspberry Pi": "raspberrypi",
    "LaTeX": "latex",
    "Zig": "zig",
    "Rust": "rust",
    "C": "c",
    "C++": "cplusplus",
    "Bash": "gnubash",
    "Docker": "docker",
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "HTML": "html5",
    "Go": "go",
    "Lua": "lua",
}

DEFAULTS = {
    "main_count": 4,
    "sub_count": 8,
    "half_life_days": 270,
    "main_min": 0.25,
    "sub_min": 0.05,
    "ignore_languages": [
        "Markdown",
        "JSON",
        "YAML",
        "Text",
        "Makefile",
        "CSS",
        "SCSS",
        "Jinja",
        "Batchfile",
        "CMake",
        "Nix",
    ],
    "manual": {},
    "topic_skills": {},
}


@dataclass
class Repo:
    name: str
    source: str
    fork: bool
    archived: bool
    pushed: dt.date
    size_kb: int
    stars: int
    topics: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)


@dataclass
class Skill:
    name: str
    score: float = 0.0
    recent: float = 0.0
    repos: set[str] = field(default_factory=set)
    last_push: dt.date | None = None


def get_json(url: str, headers: dict[str, str] | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-build", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _date(text: str) -> dt.date:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def github_repos(login: str, token: str | None, get=get_json) -> list[Repo]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    repos: list[Repo] = []
    page = 1
    while True:
        batch = get(f"https://api.github.com/users/{login}/repos?per_page=100&type=owner&page={page}", headers)
        for r in batch:
            langs = get(f"https://api.github.com/repos/{login}/{r['name']}/languages", headers)
            repos.append(
                Repo(
                    name=r["name"],
                    source="github",
                    fork=r["fork"],
                    archived=r.get("archived", False),
                    pushed=_date(r.get("pushed_at") or r["updated_at"]),
                    size_kb=r.get("size", 0),
                    stars=r.get("stargazers_count", 0),
                    topics=r.get("topics") or [],
                    languages=langs,
                )
            )
        if len(batch) < 100:
            return repos
        page += 1


def forgejo_repos(base_url: str, login: str, token: str | None, get=get_json) -> list[Repo]:
    """Public repositories of a Forgejo/Gitea user (private ones need a token)."""
    api = base_url.rstrip("/") + "/api/v1"
    headers = {"Authorization": f"token {token}"} if token else {}
    repos: list[Repo] = []
    page = 1
    while True:
        batch = get(f"{api}/users/{login}/repos?page={page}&limit=50", headers)
        if not batch:
            return repos
        for r in batch:
            owner = r.get("owner", {}).get("login", login)
            langs = get(f"{api}/repos/{owner}/{r['name']}/languages", headers)
            topics = r.get("topics")
            if topics is None:
                topics = get(f"{api}/repos/{owner}/{r['name']}/topics", headers).get("topics", [])
            repos.append(
                Repo(
                    name=r["name"],
                    source="forgejo",
                    fork=r.get("fork", False),
                    archived=r.get("archived", False),
                    pushed=_date(r["updated_at"]),
                    size_kb=r.get("size", 0),
                    stars=r.get("stars_count", 0),
                    topics=topics or [],
                    languages=langs or {},
                )
            )
        page += 1


def gather(cfg: dict, get=None) -> list[Repo]:
    """Repositories of every configured source. A source that fails is skipped with a warning."""
    get = get or get_json
    repos: list[Repo] = []
    sources = [{"type": "github", "login": cfg["login"]}, *cfg.get("extra_sources", [])]
    for src in sources:
        if not src.get("enabled", True):
            continue
        token = os.environ.get(src.get("token_env", "")) if src.get("token_env") else None
        if src["type"] == "github":
            token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        try:
            if src["type"] == "github":
                repos += github_repos(src["login"], token, get)
            elif src["type"] == "forgejo":
                repos += forgejo_repos(src["base_url"], src["login"], token, get)
            else:
                print(f"warning: unknown source type {src['type']!r}")
        except (urllib.error.URLError, OSError, KeyError, ValueError) as err:
            print(f"warning: source {src.get('base_url') or src['type']} skipped: {err}")
    return repos


def compute(repos: list[Repo], cfg: dict, today: dt.date) -> tuple[list[dict], list[dict]]:
    """Return (main, sub) as plain dicts for the skills card."""
    opt = {**DEFAULTS, **cfg.get("skills", {})}
    ignore = set(opt["ignore_languages"])
    topic_skills = {k.lower(): v for k, v in opt["topic_skills"].items()}
    skills: dict[str, Skill] = {}

    def add(name: str, weight: float, repo: Repo, recent: bool) -> None:
        s = skills.setdefault(name, Skill(name))
        s.score += weight
        s.recent += weight if recent else 0.0
        s.repos.add(f"{repo.source}/{repo.name}")
        if s.last_push is None or repo.pushed > s.last_push:
            s.last_push = repo.pushed

    for repo in repos:
        if repo.fork:
            continue
        age = max(0, (today - repo.pushed).days)
        recency = max(0.15, 0.5 ** (age / opt["half_life_days"]))
        if repo.archived:
            recency *= 0.4
        weight = recency * (1 + math.log10(1 + repo.size_kb / 100)) * (1 + math.log10(1 + repo.stars))
        recent = age <= 180
        total = sum(b for lang, b in repo.languages.items() if lang not in ignore)
        for lang, nbytes in repo.languages.items():
            if lang in ignore or total == 0:
                continue
            add(RENAME.get(lang, lang), weight * nbytes / total, repo, recent)
        for topic in repo.topics:
            if topic.lower() in topic_skills:
                add(topic_skills[topic.lower()], weight * 0.6, repo, recent)

    top = max((s.score for s in skills.values()), default=1.0)
    for name, value in opt["manual"].items():
        s = skills.setdefault(name, Skill(name))
        s.score += value * top
        s.recent += value * top

    ranked = sorted(skills.values(), key=lambda s: s.score, reverse=True)
    if not ranked:
        return [], []
    best = ranked[0].score
    main = [s for s in ranked if s.score / best >= opt["main_min"]][: opt["main_count"]]
    rest = [s for s in ranked if s not in main and s.score / best >= opt["sub_min"]]
    sub = rest[: opt["sub_count"]]
    return [_main(s, today) for s in main], [_sub(s, today) for s in sub]


def _icon(name: str, icon_dir: Path | None) -> str:
    icon = ICONS.get(name, "")
    if icon and icon_dir is not None and not (icon_dir / f"{icon}.svg").exists():
        return ""
    return icon


def ago(date: dt.date, today: dt.date) -> str:
    days = (today - date).days
    if days <= 0:
        return "today"
    if days < 60:
        return f"{days}d ago"
    if days < 700:
        return f"{round(days / 30.4)} mo ago"
    return f"{days // 365}y ago"


def _trend(s: Skill, today: dt.date) -> str:
    if s.last_push is None:
        return "steady"
    days = (today - s.last_push).days
    if days <= 90 and s.score and s.recent / s.score >= 0.7:
        return "rising"
    return "steady" if days <= 365 else "resting"


ICON_DIR: Path | None = None  # set by the build script


def _main(s: Skill, today: dt.date) -> dict:
    n = len(s.repos)
    if s.last_push is None:
        meta = "daily driver"
    else:
        meta = f"{n} repo{'s' if n != 1 else ''} · {ago(s.last_push, today)}"
    return {"name": s.name, "icon": _icon(s.name, ICON_DIR), "meta": meta, "trend": _trend(s, today)}


def _sub(s: Skill, today: dt.date) -> dict:
    active = bool(s.last_push) and (today - s.last_push).days <= 90
    return {"name": s.name, "icon": _icon(s.name, ICON_DIR), "active": active}
