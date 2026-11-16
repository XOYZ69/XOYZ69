#!/usr/bin/env python3
"""Write the Markdown for the pull request preview comment.

    compare_preview.py --base BASE_DIR --head HEAD_DIR --repo OWNER/NAME \
        --base-sha SHA --preview-url URL [--changed FILE]

BASE_DIR / HEAD_DIR are checkouts (the base branch, and the pull request merged
into it) in which build_profile.py already ran. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MARKER = "<!-- profile-preview -->"
CARDS = ("hero.cards.json", "projects.cards.json")


def files(root: Path) -> dict[str, Path]:
    gen = root / "generated"
    return {str(p.relative_to(gen)): p for p in sorted(gen.rglob("*")) if p.is_file()}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kib(path: Path | None) -> str:
    return "-" if path is None else f"{path.stat().st_size / 1024:.1f} KiB"


def load(root: Path, name: str):
    p = root / "yoshida" / "cards" / name
    return json.loads(p.read_text()) if p.exists() else {"cards": []}


def data_changes(base: Path, head: Path) -> list[str]:
    out: list[str] = []
    # Hero: every frame carries the same stats, so the first card is enough.
    b_stats = (load(base, "hero.cards.json")["cards"] or [{}])[0].get("stats", [])
    h_stats = (load(head, "hero.cards.json")["cards"] or [{}])[0].get("stats", [])
    old = {s["label"]: s["value"] for s in b_stats}
    new = {s["label"]: s["value"] for s in h_stats}
    for label in sorted(old.keys() | new.keys()):
        if old.get(label) != new.get(label):
            out.append(f"- hero stat **{label}**: `{old.get(label, '-')}` to `{new.get(label, '-')}`")
    b_msg = (load(base, "hero.cards.json")["cards"] or [{}])[0].get("msg")
    h_msg = (load(head, "hero.cards.json")["cards"] or [{}])[0].get("msg")
    if b_msg != h_msg:
        out.append(f"- hero message: `{b_msg}` to `{h_msg}`")
    b_proj = {c["id"]: c for c in load(base, "projects.cards.json")["cards"]}
    h_proj = {c["id"]: c for c in load(head, "projects.cards.json")["cards"]}
    for pid in sorted(b_proj.keys() | h_proj.keys()):
        if pid not in b_proj:
            out.append(f"- project card **{pid}** added")
        elif pid not in h_proj:
            out.append(f"- project card **{pid}** removed")
        else:
            for key in sorted(b_proj[pid].keys() | h_proj[pid].keys()):
                if b_proj[pid].get(key) != h_proj[pid].get(key):
                    out.append(
                        f"- **{pid}** {key}: `{b_proj[pid].get(key, '-')}` to `{h_proj[pid].get(key, '-')}`"
                    )
    return out


def version(root: Path) -> str:
    p = root / "yoshida" / "YOSHIDA_VERSION"
    return p.read_text().strip() if p.exists() else "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--preview-url", required=True)
    ap.add_argument("--changed", help="file with the paths the pull request changes, one per line")
    args = ap.parse_args()
    base, head = Path(args.base), Path(args.head)

    b_files, h_files = files(base), files(head)
    rows, changed = [], []
    for rel in sorted(b_files.keys() | h_files.keys()):
        b, h = b_files.get(rel), h_files.get(rel)
        if b is None:
            state = "new"
        elif h is None:
            state = "removed"
        elif digest(b) != digest(h):
            state = "changed"
        else:
            state = "same"
        if state != "same":
            changed.append(rel)
        rows.append(f"| `generated/{rel}` | {state} | {kib(b)} | {kib(h)} |")

    paths = Path(args.changed).read_text().split() if args.changed else []
    v_old, v_new = version(base), version(head)
    design_touched = [p for p in paths if p.startswith("yoshida/designs/") or p.startswith("yoshida/assets/")]
    workflow_touched = [p for p in paths if p.startswith(".github/")]
    readme_touched = "README.md" in paths

    flags = []
    if v_old != v_new:
        flags.append(f"Yoshida version changes from `{v_old}` to `{v_new}`. Every card is rendered by the new version.")
    if design_touched:
        flags.append("Design or asset files change: " + ", ".join(f"`{p}`" for p in design_touched))
    if workflow_touched:
        flags.append("Workflow or script files change: " + ", ".join(f"`{p}`" for p in workflow_touched))
    if readme_touched:
        flags.append("`README.md` changes, so the profile page itself looks different after the merge.")
    major = bool(flags) and (v_old != v_new or design_touched or len(changed) > len(h_files) / 2)

    lines = [MARKER, "## Profile preview", ""]
    if major:
        lines += ["> **Large change.** " + flags[0] if flags else "> **Large change.**", ""]
    if not changed and not flags:
        lines += ["Merging this pull request changes **no generated image**.", ""]
    else:
        lines += [f"Merging this pull request changes **{len(changed)} of {len(h_files)}** generated files.", ""]
    if flags:
        lines += ["**What else changes**", ""] + [f"- {f}" for f in flags] + [""]

    lines += ["**Generated files**", "", "| file | state | before | after |", "| --- | --- | --- | --- |", *rows, ""]
    changes = data_changes(base, head)
    if changes:
        lines += ["**Data changes**", "", *changes, ""]

    raw = f"https://raw.githubusercontent.com/{args.repo}/{args.base_sha}/generated"
    shown = [r for r in changed if r == "hero.gif" or r.startswith("projects/")]
    if shown:
        lines += ["**Before and after**", ""]
        for rel in shown:
            before = f'<img src="{raw}/{rel}" width="100%">' if rel in b_files else "_not there yet_"
            after = f'<img src="{args.preview_url}/{rel}" width="100%">' if rel in h_files else "_removed_"
            lines += [f"`{rel}`", "", "| before | after |", "| --- | --- |", f"| {before} | {after} |", ""]
    lines += [
        "<sub>After the merge, the Profile workflow rebuilds these files from live GitHub data, "
        "so numbers can differ slightly from this preview.</sub>",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
