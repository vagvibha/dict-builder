"""Tests for the book-level build (createDictionary), the StarDict
comparison used for versioning, and end-to-end runs of the build script."""
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT, SCRIPTS_DIR, have_stardict_tools, write
import createDictionary
from compare_stardict import same_dictionary
from errors import DictionaryBuildError
from stats import StatsBuilder

SHLOKA_FILE = """\
# comment line
HEADER:title=Test Kavya
HEADER:type=shloka
HEADER:skip=च
HEADER:auto_shloka=false
राम च गच्छति ।
वनं प्रति ॥१॥
====
+ e:TK-01;राम
++ रामः वनं गच्छति (सीतया सह)
some note

सीता **वनम्** ॥२॥
====
+ सीता
"""

NOTES_FILE = """\
HEADER:title=Notes
HEADER:type=notes
- key1;key2
note line
- key3
another
"""


class _TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestHeaderHelpers(unittest.TestCase):
    def test_parse_bool_header(self):
        for v, expected in (("true", True), ("False", False), (" yes ", True), ("0", False)):
            with self.subTest(v=v):
                self.assertIs(createDictionary.parse_bool_header(v, "k", "f"), expected)
        with self.assertRaises(DictionaryBuildError):
            createDictionary.parse_bool_header("maybe", "k", "f")

    def test_resolve_file_type(self):
        self.assertEqual(createDictionary.resolve_file_type({'type': ' notes '}, 'shloka', 'f'), 'notes')
        self.assertEqual(createDictionary.resolve_file_type({}, 'shloka', 'f'), 'shloka')
        for headers, default in (({}, None), ({'type': 'bogus'}, None)):
            with self.subTest(headers=headers), self.assertRaises(DictionaryBuildError):
                createDictionary.resolve_file_type(headers, default, 'f')


class TestBuildBook(_TempDirTest):
    def make_book(self, meta="name: Test\n", files=None):
        book = self.root / "book"
        write(book / "meta.yaml", meta)
        for name, text in (files or {}).items():
            write(book / name, text)
        return book

    def build(self, book, **kw):
        return createDictionary.build_book(
            book, "tabfile", True, 0, stats_file=str(self.root / "out.stats"), **kw)

    def test_end_to_end_tabfile(self):
        book = self.make_book(files={"a.txt": SHLOKA_FILE, "b.txt": NOTES_FILE})
        out, meta = self.build(book)
        self.assertEqual(meta['name'], "Test")
        lines = [l for l in out.split("\n") if l]
        self.assertEqual(len(lines), 4)

        keys = lines[0].split("\t")[0].split("|")
        # auto_shloka=false: only '+' and '++' keys; '(सीतया सह)' dropped; 'च' skipped
        self.assertEqual(sorted(keys), sorted(["TK-01", "raama", "raamaH", "vanaM", "gachChati"]))
        self.assertIn("<br>[Test Kavya]", lines[0])
        self.assertNotIn("+ e:TK-01", lines[0])
        # bold markup converted in the entry body
        self.assertIn("<b>वनम्</b>", lines[1])
        self.assertEqual(lines[1].split("\t")[0], "siitaa")
        self.assertTrue(lines[2].startswith("key1(eng)|key2(eng)\t"))

    def test_stats_file(self):
        book = self.make_book(files={"a.txt": SHLOKA_FILE, "b.txt": NOTES_FILE})
        self.build(book)
        self.assertEqual((self.root / "out.stats").read_text(encoding="utf-8"),
                         "a.txt: 2, 6\nb.txt: 2, 3\nTOTAL: 4, 9 (synonly: 5)\n")

    def test_write_stats_includes_bad_count(self):
        b = StatsBuilder()
        b.add_entry("x.txt", ["a"])
        b.add_malformed_entry("x.txt")
        path = self.root / "s.stats"
        createDictionary.write_stats_to_file(b, str(path))
        self.assertEqual(path.read_text(), "x.txt: 2, 1, 1\nTOTAL: 2, 1 (synonly: -1), 1\n")

    def test_default_type_from_meta(self):
        book = self.make_book("name: T\ntype: notes\n", {"a.txt": "- k\nbody"})
        out, _ = self.build(book)
        self.assertTrue(out.startswith("k(eng)\t"))

    def test_meta_skip_applies_to_shloka(self):
        book = self.make_book("name: T\ntype: shloka\nskip:\n  - गच्छति\n", {"a.txt": "राम गच्छति"})
        out, _ = self.build(book)
        self.assertTrue(out.startswith("raama\t"))

    def test_folders(self):
        book = self.make_book("name: T\ntype: notes\nfolders:\n  - sub\n",
                              {"a.txt": "- k1\nx", "sub/b.txt": "- k2\ny"})
        out, _ = self.build(book)
        self.assertIn("k2(eng)", out)

    def test_only_file(self):
        book = self.make_book("name: T\ntype: notes\n", {"a.txt": "- k1\nx", "b.txt": "- k2\ny"})
        out, _ = self.build(book, only_file="b.txt")
        self.assertNotIn("k1", out)
        with self.assertRaises(DictionaryBuildError):
            self.build(book, only_file="nosuch.txt")

    def test_errors_carry_file_and_line(self):
        cases = {
            "unknown header": ("HEADER:bogus=1\n- k\nx", 1),
            "bad auto_shloka": ("HEADER:type=shloka\nHEADER:auto_shloka=maybe\nx", None),
            "no type": ("- k\nx", 1),
            "unmatched bold": ("HEADER:type=notes\n- k\n**x", 3),
        }
        for label, (text, line) in cases.items():
            with self.subTest(label):
                book = self.make_book(files={"a.txt": text})
                with self.assertRaises(DictionaryBuildError) as ctx:
                    self.build(book)
                self.assertTrue(ctx.exception.file.endswith("a.txt"))
                if line:
                    self.assertEqual(ctx.exception.line, line)

    def test_no_input_files(self):
        with self.assertRaises(DictionaryBuildError):
            self.build(self.make_book())

    def test_cli_exit_code_on_error(self):
        book = self.make_book(files={"a.txt": "- k\nx"})
        res = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "createDictionary.py"), "--dict-dir", str(book),
             "-o", str(self.root / "o.tsv")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("a.txt:1", res.stderr)
        self.assertFalse((self.root / "o.tsv").exists())


class TestCompareStardict(_TempDirTest):
    def make_dict(self, name, description="v1", body=b"body", idx=b"idx", extra=None):
        d = self.root / name
        d.mkdir()
        (d / "x.ifo").write_text(f"StarDict's dict ifo file\nbookname=X\ndescription={description}\n")
        (d / "x.idx").write_bytes(idx)
        with gzip.GzipFile(d / "x.dict.dz", "wb", mtime=time.time()) as f:
            f.write(body)
        if extra:
            (d / extra).write_bytes(b"")
        return d

    def test_same_content_different_version_and_gzip_header(self):
        a = self.make_dict("a", description="v1")
        time.sleep(1.1)  # different gzip mtime
        b = self.make_dict("b", description="v2")
        self.assertNotEqual((a / "x.dict.dz").read_bytes(), (b / "x.dict.dz").read_bytes())
        self.assertTrue(same_dictionary(a, b))

    def test_differences_detected(self):
        a = self.make_dict("a")
        for label, kw in (("body", {"body": b"other"}), ("idx", {"idx": b"i2"}),
                          ("extra file", {"extra": "x.syn"})):
            with self.subTest(label):
                b = self.make_dict("b_" + label.replace(" ", ""), **kw)
                self.assertFalse(same_dictionary(a, b))

    def test_missing_old(self):
        self.assertFalse(same_dictionary(self.root / "nosuch", self.make_dict("a")))


def _env_with_current_python():
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    env.pop("PUBLISHED_DIR", None)
    return env


@unittest.skipUnless(have_stardict_tools(), "needs pyglossary + dictzip")
class TestBuildScript(_TempDirTest):
    """Runs scripts/build_dictionaries.sh on a throwaway copy of the repo."""

    def setUp(self):
        super().setUp()
        shutil.copytree(SCRIPTS_DIR, self.root / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        write(self.root / "content/meta.yaml", "dictionaries:\n  - test\n")
        write(self.root / "content/test/meta.yaml", "name: Test\n")
        write(self.root / "content/test/a.txt", SHLOKA_FILE)

    def build(self):
        res = subprocess.run(["bash", str(self.root / "scripts/build_dictionaries.sh")],
                             capture_output=True, text=True, env=_env_with_current_python())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return (self.root / "build/changed_dictionaries.txt").read_text().split()

    def publish(self):
        shutil.rmtree(self.root / "dictionaries", ignore_errors=True)
        shutil.copytree(self.root / "build/stardict", self.root / "dictionaries")

    def test_versioning(self):
        out = self.root / "build/stardict/test"

        self.assertEqual(self.build(), ["test"])
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["test.dict.dz", "test.idx", "test.ifo", "test.syn"])
        stats = (self.root / "content/test/test.stats").read_text(encoding="utf-8")
        self.assertIn("TOTAL: 2, 6", stats)
        self.assertEqual(list((self.root / "build").glob("temp_*")), [])
        self.publish()

        # Rebuild with no content change: published files reused byte-for-byte.
        time.sleep(1.1)
        self.assertEqual(self.build(), [])
        for f in out.iterdir():
            self.assertEqual(f.read_bytes(), (self.root / "dictionaries/test" / f.name).read_bytes())

        # Content change: new version.
        with open(self.root / "content/test/a.txt", "a", encoding="utf-8") as f:
            f.write("\nनवः श्लोकः ॥३॥\n====\n+ नव\n")
        self.assertEqual(self.build(), ["test"])
        self.assertFalse(same_dictionary(self.root / "dictionaries/test", out))

    def test_bad_dictionary_list_fails(self):
        write(self.root / "content/meta.yaml", "dictionaries:\n  - nosuch\n")
        res = subprocess.run(["bash", str(self.root / "scripts/build_dictionaries.sh")],
                             capture_output=True, text=True, env=_env_with_current_python())
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("nosuch", res.stderr)


if __name__ == "__main__":
    unittest.main()
