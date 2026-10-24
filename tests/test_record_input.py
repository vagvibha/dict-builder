"""Tests for the 'record' input format (record_input.py)."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PassthroughTranslator, write
from errors import DictionaryBuildError
import createDictionary
import record_input

# Tidied sheet rows (as sheets.tidy returns them).
ROWS = [
    ["title", "Dhatu notes", "keys", "Words", "entry", "Entry"],
    ["Added", "Words", "Entry", "Note", "", ""],
    ["2026", "कृ;करोति", "to **do**", "", "", ""],
    ["", "", "", "", "", ""],                                  # empty row: left out
    ["", "", "flashcard only (no keys)", "", "", ""],
    ["2026", "e:Ab-1 ;", "line one\n\nline three\n- dash, fine", "a: b", "", ""],
]

TEXT = """\
# GENERATED
HEADER:type=record
HEADER:title=Dhatu notes
HEADER:keys=Words
HEADER:entry=Entry

.--- कृ;करोति
.Added: 2026
.Words: कृ;करोति
.Entry: to **do**

.---
.Entry: flashcard only (no keys)

.--- e:Ab-1 ;
.Added: 2026
.Words: e:Ab-1 ;
.Entry: line one

line three
- dash, fine
.Note: a: b
"""


class TestRowsToText(unittest.TestCase):
    def test_text(self):
        self.assertEqual(record_input.rows_to_text(ROWS, ["GENERATED"]), TEXT)

    def test_round_trip(self):
        _, rest, n = record_input.utils.read_header(TEXT, record_input.RECORD_HEADERS)
        cells = [r["cells"] for r in record_input.parse_records(rest, n + 1)]
        header = ROWS[1]
        expected = [{h: v for h, v in zip(header, row) if h and v}
                    for row in ROWS[2:] if any(row)]
        self.assertEqual(cells, expected)

    def test_lang_and_no_title(self):
        text = record_input.rows_to_text([["keys", "K", "entry", "E", "lang", "en"],
                                          ["K", "E"], ["w", "x"]])
        self.assertEqual(text, "HEADER:type=record\nHEADER:lang=en\nHEADER:keys=K\n"
                               "HEADER:entry=E\n\n.--- w\n.K: w\n.E: x\n")

    def test_errors(self):
        meta = ["keys", "K", "entry", "E"]
        cases = {
            "empty": ([], "the tab is empty"),
            "header row as row 1": ([["Words", "Entry"], ["क", "x"]], "unsupported key 'Words'"),
            "missing entry key": ([["keys", "K"]], "missing 'entry'"),
            "key twice": ([["keys", "K", "keys", "L", "entry", "E"]], "given twice"),
            "no value": ([["keys", "K", "entry", ""]], "no value for 'entry'"),
            "value without key": ([meta + ["", "x"]], "has no key"),
            "no header row": ([meta], "no column header row"),
            "unknown column": ([meta, ["K", "F"]], "row 2: no column 'E'"),
            "duplicate column": ([meta, ["K", "E", "E"]], "column C: column name 'E' used twice"),
            "colon": ([meta, ["K", "E", "a:b"]], "column C: column name 'a:b'"),
            "dash": ([meta, ["K", "E", "-x"]], "start with '-'"),
            "unnamed column with data": ([meta, ["K", "E", ""], ["k", "x", "y"]],
                                         "column C: the column has data but no name"),
        }
        for label, (rows, msg) in cases.items():
            with self.subTest(label):
                with self.assertRaises(DictionaryBuildError) as ctx:
                    record_input.rows_to_text(rows)
                self.assertIn(msg, str(ctx.exception))

    def test_row_problems_all_reported(self):
        rows = [["keys", "K", "entry", "E"], ["K", "E", "N"],
                ["k1", "x", "ok\n.not ok"],
                ["k2", ""],
                ["k3", "#N/A"],
                ["#REF!", "x"],
                ["k5", "**x"],
                [".k6", ".fine on the first line"]]
        with self.assertRaises(DictionaryBuildError) as ctx:
            record_input.rows_to_text(rows)
        self.assertEqual(str(ctx.exception).split("\n    "), [
            "problems in the sheet:",
            "row 3, column C (N): line 2 of the cell starts with '.' "
            "(not allowed after a cell's first line)",
            "row 4: no entry ('E') for keys 'k2'",
            "row 5: column 'E' shows a spreadsheet error '#N/A'",
            "row 6: column 'K' shows a spreadsheet error '#REF!'",
            "row 7: unmatched '**' marker (no closing '**' found for it)",
        ])

    def test_column_letters(self):
        self.assertEqual([record_input.column_letter(i) for i in (0, 25, 26, 27, 701, 702)],
                         ["A", "Z", "AA", "AB", "ZZ", "AAA"])


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def entries(self, text):
        return record_input.read_record_file(self.d / "r.txt", text, PassthroughTranslator())


class TestRead(_Tmp):
    def test_entries(self):
        self.assertEqual(self.entries(TEXT), [
            {"words": ["करोति", "कृ"], "entry": "to <b>do</b><br>कृ; करोति<br>[Dhatu notes]"},
            {"words": ["e:Ab-1"],
             "entry": "line one<br><br>line three<br>- dash, fine<br>e:Ab-1<br>[Dhatu notes]"},
        ])

    def test_errors(self):
        head = "HEADER:type=record\nHEADER:keys=K\nHEADER:entry=E\n\n"
        cases = {
            "bad dot line": (head + ".--- k\n.K: k\n.E: x\n.oops\n", 8, "bad line '.oops'"),
            "marker without space": (head + ".---k\n", 5, "bad line"),
            "field before marker": (head + ".K: k\n", 5, "before the first"),
            "text before marker": (head + "stray\n", 5, "text outside a field"),
            "text after marker": (head + ".--- k\nstray\n", 6, "text outside a field"),
            "field twice": (head + ".--- k\n.K: k\n.K: j\n", 7, "given twice"),
            "no entry": (head + ".--- k\n.K: k\n", 5, "no entry"),
            "sheet error": (head + ".---\n.K: #N/A\n", 5, "spreadsheet error"),
            "bad bold": (head + ".--- k\n.K: k\n.E: a\nb **c\n", 8, "unmatched"),
            "no keys header": ("HEADER:type=record\nHEADER:entry=E\n", 1, "HEADER:keys="),
            "unsupported header": ("HEADER:type=record\nHEADER:skip=x\n", 2,
                                   "unsupported header key 'skip'"),
            "not record": ("HEADER:type=notes\n", 1, "not a record file"),
        }
        for label, (text, line, msg) in cases.items():
            with self.subTest(label):
                with self.assertRaises(DictionaryBuildError) as ctx:
                    self.entries(text)
                self.assertEqual(ctx.exception.line, line)
                self.assertIn(msg, str(ctx.exception))
                self.assertIn("r.txt", str(ctx.exception))


class TestBuildBook(_Tmp):
    def test_record_next_to_notes(self):
        book = self.d / "book"
        write(book / "meta.yaml", "name: Book\ntype: notes\nfolders: [sub]\n")
        write(book / "a.txt", "HEADER:title=T\n- कर्म\nnote\n")
        write(book / "sub/w.txt", "# generated\nHEADER:type=record\nHEADER:lang=en\n"
                                  "HEADER:keys=K\nHEADER:entry=E\n\n"
                                  ".--- hello;e:X\n.K: hello;e:X\n.E: greeting\n")
        write(book / "old.csv", "not read any more\n")
        stats = self.d / "s.stats"
        out, _ = createDictionary.build_book(book, "tabfile", True, 0, stats_file=str(stats))
        self.assertEqual([l for l in out.split("\n") if l], [
            "karma\t<br>note<br>कर्म<br>[T]",
            "X|hello\tgreeting<br>hello; e:X<br>[unknown]",   # lang=en: no (eng)
        ])
        self.assertEqual(stats.read_text(encoding="utf-8"),
                         "a.txt: 1, 1\nsub/w.txt: 1, 2\nTOTAL: 2, 3 (synonly: 1)\n")

    def test_keys_header_only_for_record(self):
        book = self.d / "book"
        write(book / "meta.yaml", "name: Book\ntype: notes\n")
        write(book / "a.txt", "HEADER:keys=K\n- कर्म\nnote\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            createDictionary.build_book(book, "tabfile", False, 0, stats_file=None)
        self.assertIn("a.txt:1: HEADER:keys is only for record files", str(ctx.exception))

    def test_record_error_has_location(self):
        book = self.d / "book"
        write(book / "meta.yaml", "name: Book\n")
        write(book / "w.txt", "HEADER:type=record\nHEADER:keys=K\nHEADER:entry=E\n\n"
                              ".--- k\n.K: k\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            createDictionary.build_book(book, "tabfile", False, 0, stats_file=None)
        self.assertIn("w.txt:5: no entry", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
