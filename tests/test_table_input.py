"""Tests for the 'table' (.csv) input format."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PassthroughTranslator, write
from errors import DictionaryBuildError
import createDictionary
import table_input

GOOD = (
    "title,Dhatu notes,keys,Words,entry,Entry,,\n"
    "Added,Words,Entry,Ignored\n"
    "2026,कृ;करोति,to **do**,x\n"
    ",,,\n"
    ",,flashcard only (no keys),\n"
    '2026, e:Ab-1 ; ,"line one\n'
    'line two",\n'
)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def csv(self, text, name="t.csv"):
        return write(self.d / name, text)


class TestReadTable(_Tmp):
    def test_good(self):
        headers, records = table_input.read_table(self.csv(GOOD))
        self.assertEqual(headers, {"title": "Dhatu notes"})
        self.assertEqual(records, [(3, (["कृ", "करोति"], "to <b>do</b>")),
                                   (6, (["e:Ab-1"], "line one\nline two"))])

    def test_bom_and_column_order(self):
        _, records = table_input.read_table(self.csv(
            "﻿entry,E,keys,K,lang,en\nE,K\nmeaning,word\n"))
        self.assertEqual(records, [(3, (["word"], "meaning"))])

    def test_errors(self):
        cases = {
            "empty": ("", 1, "empty"),
            "header row as row 1": ("Words,Entry\nक,x\n", 1, "unsupported key 'Words'"),
            "missing entry key": ("keys,K\nK\n", 1, "missing 'entry'"),
            "key twice": ("keys,K,keys,L,entry,E\n", 1, "given twice"),
            "no value": ("keys,K,entry,\n", 1, "no value for 'entry'"),
            "value without key": ("keys,K,entry,E,,x\n", 1, "has no key"),
            "no header row": ("keys,K,entry,E\n", 2, "no column header"),
            "unknown column": ("keys,K,entry,E\nK,F\n", 2, "no column 'E'"),
            "duplicate column": ("keys,K,entry,E\nK,E,E\n", 2, "more than one column 'E'"),
            "no entry": ("keys,K,entry,E\nK,E\nk1,x\nk2,\n", 4, "no entry"),
            "sheet error": ("keys,K,entry,E\nK,E\nk1,#N/A\n", 3, "spreadsheet error"),
            "bad bold": ("keys,K,entry,E\nK,E\nk,x\nk,**x\n", 4, "**"),
        }
        for label, (text, line, msg) in cases.items():
            with self.subTest(label):
                with self.assertRaises(DictionaryBuildError) as ctx:
                    table_input.read_table(self.csv(text))
                self.assertEqual(ctx.exception.line, line)
                self.assertIn(msg, str(ctx.exception))

    def test_row_line_numbers_after_multiline_cell(self):
        with self.assertRaises(DictionaryBuildError) as ctx:
            table_input.read_table(self.csv('keys,K,entry,E\nK,E\nk,"a\nb\nc"\nk2,#REF!\n'))
        self.assertEqual(ctx.exception.line, 6)


class TestHandler(_Tmp):
    def test_entries(self):
        h = table_input.TableInputHandler(PassthroughTranslator(), info="t.csv")
        out = h.process_file(self.csv(GOOD))
        self.assertEqual(out, [
            {"words": ["करोति", "कृ"], "entry": "to <b>do</b><br>कृ; करोति<br>[Dhatu notes]"},
            {"words": ["e:Ab-1"], "entry": "line one<br>line two<br>e:Ab-1<br>[Dhatu notes]"},
        ])

    def test_no_title(self):
        h = table_input.TableInputHandler(PassthroughTranslator())
        out = h.process_file(self.csv("keys,K,entry,E\nK,E\nk,x\n"))
        self.assertEqual(out[0]["entry"], "x<br>k<br>[unknown]")


class TestBuildBook(_Tmp):
    def test_csv_next_to_txt(self):
        book = self.d / "book"
        write(book / "meta.yaml", "name: Book\ntype: notes\nfolders: [sub]\n")
        write(book / "a.txt", "HEADER:title=T\n- कर्म\nnote\n")
        write(book / "sub/w.csv", "lang,en,keys,K,entry,E\nK,E\nhello;e:X,greeting\n")
        stats = self.d / "s.stats"
        out, _ = createDictionary.build_book(book, "tabfile", True, 0, stats_file=str(stats))
        self.assertEqual([l for l in out.split("\n") if l], [
            "karma\t<br>note<br>कर्म<br>[T]",
            "X|hello\tgreeting<br>hello; e:X<br>[unknown]",   # lang=en: no (eng)
        ])
        self.assertEqual(stats.read_text(encoding="utf-8"),
                         "a.txt: 1, 1\nsub/w.csv: 1, 2\nTOTAL: 2, 3 (synonly: 1)\n")

    def test_csv_error_has_location(self):
        book = self.d / "book"
        write(book / "meta.yaml", "name: Book\n")
        write(book / "w.csv", "Words,Entry\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            createDictionary.build_book(book, "tabfile", False, 0, stats_file=None)
        self.assertIn("w.csv:1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
