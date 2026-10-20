"""Tests for sheets.py / plan.py sync-sheets (Sheets API replaced by a fake)."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import write
from errors import DictionaryBuildError
import sheets
import plan


def sync_sheets(ws, content, client):
    return plan.sync_sheets(ws, content, client, log=lambda m: None)

URL = "https://docs.google.com/spreadsheets/d/SID/edit?gid={gid}#gid={gid}"
TABLE = [["title", "T", "keys", "Words", "entry", "Entry", ""],
         ["Words", "Entry", "", ""],
         ["कृ", " to do ", "", ""],
         ["", "", "", ""]]


class FakeClient:
    def __init__(self, tabs):
        self.tabs, self.calls = tabs, []

    def fetch(self, url):
        self.calls.append(url)
        value = self.tabs[sheets.parse_url(url)[1]]
        if isinstance(value, Exception):
            raise value
        return value


class _Ws(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.content = self.ws / "contents"

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, sheets_yaml):
        write(self.content / "meta.yaml", "dictionaries: [misc]\n" + sheets_yaml)

    def entry(self, path, gid, extra=""):
        return f"  - path: {path}\n    url: '{URL.format(gid=gid)}'\n{extra}"


class TestHelpers(unittest.TestCase):
    def test_parse_url(self):
        self.assertEqual(sheets.parse_url(URL.format(gid=7)), ("SID", 7))
        self.assertIsNone(sheets.parse_url("https://docs.google.com/spreadsheets/d/SID/edit"))

    def test_tidy(self):
        self.assertEqual(sheets.tidy(TABLE),
                         "title,T,keys,Words,entry,Entry\nWords,Entry,,,,\nकृ,to do,,,,\n")
        # NFC: e + combining acute -> one character
        self.assertEqual(sheets.tidy([["e\u0301"]]), "\u00e9\n")
        self.assertEqual(sheets.tidy([["a\nb", "x,y"]]), '"a\nb","x,y"\n')
        self.assertEqual(sheets.tidy([]), "")


class TestConfig(_Ws):
    def load(self, text):
        import yaml
        return sheets.load_sheets_config(yaml.safe_load(text), self.ws, self.ws / "m.yaml")

    def test_ok(self):
        out = self.load("- {path: contents/a/x.csv, url: '" + URL.format(gid=1) + "'}\n"
                        "- {path: masters/y.csv, url: '" + URL.format(gid=2) + "', fetch: false}\n")
        self.assertEqual([(s["rel"], s["fetch"]) for s in out],
                         [("contents/a/x.csv", True), ("masters/y.csv", False)])
        self.assertEqual(out[0]["path"], (self.ws / "contents/a/x.csv").resolve())

    def test_errors(self):
        u = URL.format(gid=1)
        cases = {
            "not csv": f"- {{path: a.tsv, url: '{u}'}}\n",
            "outside": f"- {{path: ../a.csv, url: '{u}'}}\n",
            "absolute": f"- {{path: /tmp/a.csv, url: '{u}'}}\n",
            "no gid": "- {path: a.csv, url: 'https://docs.google.com/spreadsheets/d/S/edit'}\n",
            "unknown key": f"- {{path: a.csv, url: '{u}', tab: x}}\n",
            "dup": f"- {{path: a.csv, url: '{u}'}}\n- {{path: ./a.csv, url: '{u}'}}\n",
            "bad fetch": f"- {{path: a.csv, url: '{u}', fetch: 'no'}}\n",
            "not list": "a: 1\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(DictionaryBuildError):
                    self.load(text)


class TestSync(_Ws):
    def test_writes_tidied_and_reports_same(self):
        self.config("sheets:\n" + self.entry("contents/misc/w.csv", 1)
                    + self.entry("masters/raw.csv", 2))
        client = FakeClient({1: TABLE, 2: [["a", "b"], ["1", "2"]]})
        written = sync_sheets(self.ws, self.content, client)
        self.assertEqual(sorted(p.name for p in written), ["raw.csv", "w.csv"])
        self.assertEqual((self.content / "misc/w.csv").read_text(encoding="utf-8"),
                         sheets.tidy(TABLE))
        self.assertEqual((self.ws / "masters/raw.csv").read_text(), "a,b\n1,2\n")
        # unchanged second time: nothing written
        self.assertEqual(sync_sheets(self.ws, self.content, client), [])

    def test_all_or_nothing(self):
        self.config("sheets:\n" + self.entry("contents/misc/a.csv", 1)
                    + self.entry("contents/misc/b.csv", 2))
        client = FakeClient({1: TABLE, 2: RuntimeError("HTTP 500")})
        with self.assertRaises(DictionaryBuildError) as ctx:
            sync_sheets(self.ws, self.content, client)
        self.assertIn("b.csv: RuntimeError: HTTP 500", str(ctx.exception))
        self.assertFalse((self.content / "misc/a.csv").exists())

    def test_table_files_are_validated(self):
        self.config("sheets:\n" + self.entry("contents/misc/a.csv", 1)
                    + self.entry("masters/not-a-table.csv", 2))
        bad = [["Words", "Entry"], ["कृ", "x"]]          # header row in row 1
        client = FakeClient({1: bad, 2: bad})
        with self.assertRaises(DictionaryBuildError) as ctx:
            sync_sheets(self.ws, self.content, client)
        msg = str(ctx.exception)
        self.assertIn("contents/misc/a.csv:", msg)
        self.assertIn("a.csv:1: row 1 (metadata)", msg)
        self.assertNotIn("not-a-table", msg)        # outside contents/: not a table

    def test_fetch_false_keeps_file(self):
        write(self.content / "misc/a.csv", "old, broken\n")
        self.config("sheets:\n" + self.entry("contents/misc/a.csv", 1, "    fetch: false\n")
                    + self.entry("contents/misc/b.csv", 2))
        client = FakeClient({2: TABLE})
        sync_sheets(self.ws, self.content, client)
        self.assertEqual(client.calls, [URL.format(gid=2)])
        self.assertEqual((self.content / "misc/a.csv").read_text(), "old, broken\n")

    def test_empty_tab_and_no_config(self):
        self.config("")
        self.assertEqual(sync_sheets(self.ws, self.content, FakeClient({})), [])
        self.config("sheets:\n" + self.entry("masters/a.csv", 1))
        with self.assertRaises(DictionaryBuildError):
            sync_sheets(self.ws, self.content, FakeClient({1: [["", ""]]}))


class TestClientCredentials(unittest.TestCase):
    def test_no_credentials(self):
        import os
        saved = {k: os.environ.pop(k, None)
                 for k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS")}
        try:
            with self.assertRaises(DictionaryBuildError) as ctx:
                sheets.SheetsClient()
            self.assertRegex(str(ctx.exception), "no credentials|missing libraries")
        finally:
            os.environ.update({k: v for k, v in saved.items() if v is not None})


if __name__ == "__main__":
    unittest.main()
