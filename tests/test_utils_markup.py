import tempfile
import unittest
from pathlib import Path

from tests.helpers import write
import markup
import utils
from errors import DictionaryBuildError


class TestReadHeader(unittest.TestCase):
    ALLOWED = {'title', 'skip', 'type'}

    def test_no_header(self):
        data = "- word1 ((syn1))\n# not a header comment"
        self.assertEqual(utils.read_header(data, self.ALLOWED), ({}, data, 0))

    def test_headers_and_comments(self):
        data = "# c1\n# c2\nHEADER:title=Rigveda\nHEADER:skip=a;b\n- agni\n  notes"
        headers, rest, consumed = utils.read_header(data, self.ALLOWED)
        self.assertEqual(headers, {'title': 'Rigveda', 'skip': 'a;b'})
        self.assertEqual(rest, "- agni\n  notes")
        self.assertEqual(consumed, 4)

    def test_value_may_contain_equals(self):
        headers, _, _ = utils.read_header("HEADER:title=a=b\n- x", self.ALLOWED)
        self.assertEqual(headers, {'title': 'a=b'})

    def test_header_block_ends_at_first_non_header(self):
        data = "HEADER:title=M\n- line\nHEADER:type=notes\n"
        headers, rest, _ = utils.read_header(data, self.ALLOWED)
        self.assertEqual(headers, {'title': 'M'})
        self.assertEqual(rest, "- line\nHEADER:type=notes\n")

    def test_unsupported_key(self):
        with self.assertRaises(DictionaryBuildError) as ctx:
            utils.read_header("HEADER:title=x\nHEADER:bogus=1\n- a", self.ALLOWED)
        self.assertIn("bogus", str(ctx.exception))
        self.assertEqual(ctx.exception.line, 2)

    def test_malformed(self):
        for bad in ("HEADER:title\n- a", "HEADER:title=\n- a", "HEADER:title=  \n- a"):
            with self.subTest(bad=bad), self.assertRaises(DictionaryBuildError):
                utils.read_header(bad, self.ALLOWED)


class TestSplitHelpers(unittest.TestCase):
    def test_split_with_line_numbers(self):
        text = "a\nb\n\nc\n\n\n\nd"
        self.assertEqual(utils.split_with_line_numbers(text, "\n\n"),
                         [(1, "a\nb"), (4, "c"), (8, "d")])

    def test_split_empty(self):
        self.assertEqual(utils.split_with_line_numbers("", "\n\n"), [])

    def test_enumerate_nonblank_lines(self):
        self.assertEqual(utils.enumerate_nonblank_lines("a\n\n  b  \n"), [(1, "a"), (3, "b")])


class TestConfigLoading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_book_meta_defaults(self):
        write(self.root / "meta.yaml", "name: Sahitya\n")
        self.assertEqual(utils.load_book_meta(self.root),
                         {"name": "Sahitya", "type": None, "lang": None, "skip": [], "folders": []})

    def test_book_meta_fallback_defaults(self):
        self.assertEqual(utils.load_book_meta(self.root, {"name": "Ext", "type": "notes"})["type"],
                         "notes")
        # A real meta.yaml wins over the defaults.
        write(self.root / "meta.yaml", "name: Own\n")
        self.assertEqual(utils.load_book_meta(self.root, {"name": "Ext"})["name"], "Own")

    def test_book_meta_missing(self):
        with self.assertRaises(DictionaryBuildError):
            utils.load_book_meta(self.root)

    def test_book_meta_errors(self):
        for text in ("type: notes\n", "name: X\ntype: bogus\n"):
            with self.subTest(text=text):
                write(self.root / "meta.yaml", text)
                with self.assertRaises(DictionaryBuildError):
                    utils.load_book_meta(self.root)

    def test_discover_input_files(self):
        write(self.root / "b.txt", "")
        write(self.root / "a.txt", "")
        write(self.root / "notes.md", "")
        write(self.root / "sub/c.txt", "")
        write(self.root / "sub/deeper/d.txt", "")
        write(self.root / "other/e.txt", "")
        files = utils.discover_input_files(self.root, ["sub"])
        self.assertEqual([f.relative_to(self.root).as_posix() for f in files],
                         ["a.txt", "b.txt", "sub/c.txt"])

    def test_discover_bad_folder(self):
        with self.assertRaises(DictionaryBuildError):
            utils.discover_input_files(self.root, ["nosuch"])


class TestBoldMarkup(unittest.TestCase):
    def test_no_markup(self):
        self.assertEqual(markup.apply_bold_markup("plain"), "plain")

    def test_conversion(self):
        self.assertEqual(markup.apply_bold_markup("a **b** c **d\ne** f"),
                         "a <b>b</b> c <b>d\ne</b> f")

    def test_unmatched_reports_line(self):
        with self.assertRaises(DictionaryBuildError) as ctx:
            markup.apply_bold_markup("x\n**a** **b", filename="f.txt", line_offset=3)
        self.assertEqual(ctx.exception.line, 5)
        self.assertEqual(ctx.exception.file, "f.txt")

    def test_span_too_long(self):
        text = "**a" + "\n" * (markup.MAX_BOLD_SPAN_LINES + 1) + "b**"
        with self.assertRaises(DictionaryBuildError) as ctx:
            markup.apply_bold_markup(text)
        self.assertEqual(ctx.exception.line, 1)

    def test_strip_bold_tags(self):
        self.assertEqual(markup.strip_bold_tags("<b>a</b> b"), "a b")


class TestErrors(unittest.TestCase):
    def test_message_location(self):
        self.assertEqual(str(DictionaryBuildError("oops", file="f", line=3)), "f:3: oops")
        self.assertEqual(str(DictionaryBuildError("oops")), "oops")

    def test_with_location_fills_only_missing(self):
        e = DictionaryBuildError("oops", line=2).with_location(file="f", line=9)
        self.assertEqual((e.file, e.line), ("f", 2))


if __name__ == "__main__":
    unittest.main()
