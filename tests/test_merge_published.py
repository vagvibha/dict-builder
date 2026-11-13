"""Tests for scripts/merge_published.py."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SCRIPTS_DIR, write

SCRIPT = SCRIPTS_DIR / "merge_published.py"


class TestMergePublished(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pub = self.root / "published"
        self.out = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, name, ids, text="v1"):
        b = self.root / name
        for i in ids:
            write(b / i / f"{i}.ifo", f"{i} {text}")
        return b

    def run_merge(self, build, group):
        return subprocess.run([sys.executable, str(SCRIPT), "--published", str(self.pub),
                               "--build", str(build), "--group", group, "--out", str(self.out)],
                              capture_output=True, text=True)

    def publish(self):
        """What CI does after a 'changed': the out tree becomes the branch."""
        import shutil
        shutil.rmtree(self.pub, ignore_errors=True)
        shutil.copytree(self.out, self.pub)

    def tree(self):
        return sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file())

    def test_groups_share_the_tree(self):
        res = self.run_merge(self.build("b1", ["a", "b"]), "personal")
        self.assertEqual(res.stdout.strip(), "changed", res.stderr)   # nothing published yet
        self.publish()
        res = self.run_merge(self.build("b2", ["ac-x"]), "ac")
        self.assertEqual(res.stdout.strip(), "changed")
        self.assertEqual(self.tree(), ["dictionaries/a/a.ifo", "dictionaries/ac-x/ac-x.ifo",
                                       "dictionaries/b/b.ifo", "groups/ac.txt",
                                       "groups/personal.txt"])
        self.publish()

        # Rebuilding personal with 'b' dropped removes only 'b'.
        res = self.run_merge(self.build("b3", ["a"]), "personal")
        self.assertEqual(res.stdout.strip(), "changed")
        self.assertEqual(self.tree(), ["dictionaries/a/a.ifo", "dictionaries/ac-x/ac-x.ifo",
                                       "groups/ac.txt", "groups/personal.txt"])
        self.assertEqual((self.out / "groups/personal.txt").read_text(), "a\n")

    def test_unchanged(self):
        self.run_merge(self.build("b1", ["a"]), "personal")
        self.publish()
        res = self.run_merge(self.build("b2", ["a"]), "personal")
        self.assertEqual(res.stdout.strip(), "unchanged")
        res = self.run_merge(self.build("b3", ["a"], text="v2"), "personal")
        self.assertEqual(res.stdout.strip(), "changed")

    def test_first_run_without_list_keeps_unknown_dictionaries(self):
        # A tree published before groups existed: only rebuilt ids are replaced.
        write(self.pub / "dictionaries/old/old.ifo", "old")
        write(self.pub / "dictionaries/a/a.ifo", "a v0")
        res = self.run_merge(self.build("b1", ["a"]), "personal")
        self.assertEqual(res.stdout.strip(), "changed")
        self.assertEqual(self.tree(), ["dictionaries/a/a.ifo", "dictionaries/old/old.ifo",
                                       "groups/personal.txt"])
        self.assertEqual((self.out / "dictionaries/a/a.ifo").read_text(), "a v1")

    def test_conflict(self):
        self.run_merge(self.build("b1", ["a"]), "personal")
        self.publish()
        res = self.run_merge(self.build("b2", ["a"]), "ac")
        self.assertEqual(res.returncode, 2)
        self.assertIn("already published by group 'personal'", res.stderr)

    def test_bad_group(self):
        res = self.run_merge(self.build("b1", ["a"]), "../x")
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
