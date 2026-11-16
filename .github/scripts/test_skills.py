"""Tests for skills.py. Run: python -m unittest discover -s .github/scripts -p 'test_*.py'"""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills  # noqa: E402

TODAY = dt.date(2026, 11, 16)


def repo(name, pushed, langs, size=500, stars=0, topics=(), source="github", fork=False):
    return skills.Repo(name, source, fork, False, pushed, size, stars, list(topics), langs)


class ComputeTest(unittest.TestCase):
    cfg = {"skills": {"manual": {}, "topic_skills": {"arduino": "Arduino"}}}

    def test_recent_big_project_beats_old_one(self):
        repos = [
            repo("old", dt.date(2022, 1, 1), {"Rust": 100_000}),
            repo("new", dt.date(2026, 11, 10), {"Zig": 60_000}),
        ]
        main, _ = skills.compute(repos, self.cfg, TODAY)
        self.assertEqual(main[0]["name"], "Zig")
        self.assertEqual(main[0]["trend"], "rising")

    def test_forks_and_ignored_languages_do_not_count(self):
        repos = [
            repo("fork", TODAY, {"Go": 1_000_000}, fork=True),
            repo("docs", TODAY, {"Markdown": 5000, "Python": 100}),
        ]
        main, sub = skills.compute(repos, self.cfg, TODAY)
        names = [s["name"] for s in main + sub]
        self.assertEqual(names, ["Python"])

    def test_topics_add_skills_and_sources_merge(self):
        repos = [
            repo("a", dt.date(2026, 11, 1), {"C++": 9000}, topics=["arduino"]),
            repo("b", dt.date(2026, 10, 1), {"Python": 9000}, source="forgejo"),
        ]
        main, sub = skills.compute(repos, self.cfg, TODAY)
        names = {s["name"] for s in main + sub}
        self.assertEqual(names, {"C++", "Arduino", "Python"})

    def test_tiers_respect_counts(self):
        repos = [repo(f"r{i}", TODAY, {f"L{i}": 1000 * (20 - i)}) for i in range(15)]
        cfg = {"skills": {"main_min": 0.0, "sub_min": 0.0}}
        main, sub = skills.compute(repos, cfg, TODAY)
        self.assertEqual((len(main), len(sub)), (4, 8))

    def test_manual_skill_has_no_repos(self):
        cfg = {"skills": {"manual": {"Git": 0.5}}}
        main, _ = skills.compute([repo("a", TODAY, {"Zig": 1000})], cfg, TODAY)
        git = next(s for s in main if s["name"] == "Git")
        self.assertEqual((git["meta"], git["trend"]), ("daily driver", "steady"))

    def test_ago(self):
        self.assertEqual(skills.ago(TODAY, TODAY), "today")
        self.assertEqual(skills.ago(dt.date(2026, 11, 6), TODAY), "10d ago")
        self.assertEqual(skills.ago(dt.date(2026, 5, 16), TODAY), "6 mo ago")
        self.assertEqual(skills.ago(dt.date(2023, 11, 16), TODAY), "3y ago")


class ForgejoTest(unittest.TestCase):
    def test_pagination_and_fields(self):
        def get(url, headers=None):
            if "/users/me/repos?page=1" in url:
                return [{"name": "x", "updated_at": "2026-10-01T10:00:00+02:00", "size": 12, "stars_count": 1}]
            if "/users/me/repos" in url:
                return []
            if url.endswith("/languages"):
                return {"Python": 10}
            if url.endswith("/topics"):
                return {"topics": ["arduino"]}
            raise AssertionError(url)

        repos = skills.forgejo_repos("https://git.example.org/", "me", "tok", get)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].topics, ["arduino"])
        self.assertEqual(repos[0].pushed, dt.date(2026, 10, 1))


if __name__ == "__main__":
    unittest.main()
