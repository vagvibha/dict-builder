"""Tests for plan.py: workspace config, external sources, fetching."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import write
from errors import DictionaryBuildError
from plan import build_plan, fetch_sources, load_workspace_config


def make_git_repo(path: Path, files: dict) -> str:
    """Creates a git repo with `files` committed; returns its HEAD sha."""
    for name, text in files.items():
        write(path / name, text)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True,
                                    text=True).stdout.strip()
    run("init", "-q", "-b", "main")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    return run("rev-parse", "HEAD")


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.content = self.ws / "content"
        self.external = self.ws / "external"

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, text):
        write(self.content / "meta.yaml", text)

    def local(self, name, meta="name: X\n"):
        write(self.content / name / "meta.yaml", meta)


class TestWorkspaceConfig(_Workspace):
    def test_local_only(self):
        self.config("dictionaries:\n  - a\n")
        cfg = load_workspace_config(self.content)
        self.assertEqual((cfg["dictionaries"], cfg["sources"]), (["a"], []))

    def test_source_defaults(self):
        self.config("sources:\n  - name: repoA\n    repo: https://x/repoA.git\n")
        src = load_workspace_config(self.content)["sources"][0]
        self.assertEqual(src, {"name": "repoA", "repo": "https://x/repoA.git", "ref": None,
                               "manifest": "dict/meta.yaml", "suffix": "-repoA",
                               "dictionaries": None, "defaults": {}})

    def test_errors(self):
        cases = {
            "empty": "other: 1\n",
            "no repo": "sources:\n  - name: a\n",
            "bad name": "sources:\n  - name: 'a b'\n    repo: r\n",
            "unknown key": "sources:\n  - name: a\n    repo: r\n    branch: x\n",
            "dup source": "sources:\n  - {name: a, repo: r}\n  - {name: a, repo: s}\n",
            "bad default type": "sources:\n  - name: a\n    repo: r\n    defaults: {type: bogus}\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.config(text)
                with self.assertRaises(DictionaryBuildError):
                    load_workspace_config(self.content)

    def test_missing(self):
        with self.assertRaises(DictionaryBuildError):
            load_workspace_config(self.content)


class TestBuildPlan(_Workspace):
    SOURCE = ("sources:\n  - name: repoA\n    repo: r\n    suffix: -repoA-Nick\n"
              "    defaults: {type: notes}\n")

    def test_local_and_external(self):
        self.local("sahitya")
        self.config("dictionaries:\n  - sahitya\n" + self.SOURCE)
        write(self.external / "repoA/dict/meta.yaml", "dictionaries:\n  - kavya\n  - sub/blah\n")
        write(self.external / "repoA/dict/kavya/meta.yaml", "name: Kavya\n")
        write(self.external / "repoA/dict/sub/blah/a.txt", "- k\nx")

        plan = build_plan(self.content, self.external)
        self.assertEqual([(e["id"], e["source"]) for e in plan],
                         [("sahitya", None), ("kavya-repoA-Nick", "repoA"),
                          ("blah-repoA-Nick", "repoA")])
        self.assertEqual(plan[0]["dir"], self.content / "sahitya")
        self.assertEqual(plan[1]["dir"], (self.external / "repoA/dict/kavya").resolve())
        # name defaults to the id when the source provides no meta.yaml
        self.assertEqual(plan[2]["meta_defaults"], {"type": "notes", "name": "blah-repoA-Nick"})

    def test_fallback_list_when_no_manifest(self):
        self.config(self.SOURCE + "    dictionaries: [kavya]\n")
        (self.external / "repoA/dict/kavya").mkdir(parents=True)
        self.assertEqual([e["id"] for e in build_plan(self.content, self.external)],
                         ["kavya-repoA-Nick"])

    def test_errors(self):
        cases = {
            "not fetched": (self.SOURCE, {}),
            "no manifest or list": (self.SOURCE, {"repoA/README": ""}),
            "missing dir": (self.SOURCE, {"repoA/dict/meta.yaml": "dictionaries: [nosuch]\n"}),
            "escapes source": (self.SOURCE, {"repoA/dict/meta.yaml": "dictionaries: ['../..']\n"}),
            "local without meta": ("dictionaries: [nometa]\n", {}),
        }
        for label, (cfg, files) in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.external, ignore_errors=True)
                for name, text in files.items():
                    write(self.external / name, text)
                self.config(cfg)
                with self.assertRaises(DictionaryBuildError):
                    build_plan(self.content, self.external)

    def test_duplicate_ids(self):
        self.local("kavya-repoA-Nick")
        self.config("dictionaries: [kavya-repoA-Nick]\n" + self.SOURCE)
        write(self.external / "repoA/dict/meta.yaml", "dictionaries: [kavya]\n")
        (self.external / "repoA/dict/kavya").mkdir()
        with self.assertRaises(DictionaryBuildError) as ctx:
            build_plan(self.content, self.external)
        self.assertIn("duplicate", str(ctx.exception))


class TestFetch(_Workspace):
    def test_clone_then_update(self):
        upstream = self.ws / "upstream"
        sha1 = make_git_repo(upstream, {"dict/meta.yaml": "dictionaries: [a]\n", "dict/a/x.txt": "1"})
        self.config(f"sources:\n  - name: repoA\n    repo: {upstream}\n")

        self.assertEqual(fetch_sources(self.content, self.external), [("repoA", str(upstream), sha1)])
        self.assertTrue((self.external / "repoA/dict/a/x.txt").exists())

        # Upstream moves on (and removes a file); a re-fetch follows it.
        (upstream / "dict/a/x.txt").unlink()
        write(upstream / "dict/a/y.txt", "2")
        subprocess.run(["git", "add", "-A"], cwd=upstream, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "2"],
                       cwd=upstream, check=True)
        write(self.external / "repoA/local-junk.txt", "")

        (_, _, sha2), = fetch_sources(self.content, self.external)
        self.assertNotEqual(sha1, sha2)
        self.assertFalse((self.external / "repoA/dict/a/x.txt").exists())
        self.assertTrue((self.external / "repoA/dict/a/y.txt").exists())
        self.assertFalse((self.external / "repoA/local-junk.txt").exists())

    def test_ref(self):
        upstream = self.ws / "upstream"
        make_git_repo(upstream, {"f": "main"})
        subprocess.run(["git", "checkout", "-qb", "other"], cwd=upstream, check=True)
        write(upstream / "f", "other")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "o"],
                       cwd=upstream, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=upstream, check=True)

        self.config(f"sources:\n  - name: r\n    repo: {upstream}\n    ref: other\n")
        fetch_sources(self.content, self.external)
        self.assertEqual((self.external / "r/f").read_text(), "other")

    def test_bad_repo(self):
        self.config(f"sources:\n  - name: r\n    repo: {self.ws / 'nosuch'}\n")
        with self.assertRaises(DictionaryBuildError):
            fetch_sources(self.content, self.external)


if __name__ == "__main__":
    unittest.main()
