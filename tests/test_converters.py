"""Tests for scripts/converters/amarakosha_tsv_to_notes.py."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SCRIPTS_DIR, write
from errors import DictionaryBuildError

sys.path.insert(0, str(SCRIPTS_DIR / "converters"))
import amarakosha_tsv_to_notes as ak  # noqa: E402

CONVERTER = SCRIPTS_DIR / "converters" / "amarakosha_tsv_to_notes.py"

# Columns deliberately in a different order from the real export, with
# extra columns, mixed zero-padding and Devanagari digits in references.
SHLOKAS_TSV = (
    "संख्या\tश्लोकः\textra\tवर्गः\n"
    "1।04।31\tचित्तं तु चेतो हृदयं। स्वान्तं हृन्मानसं मनः॥\tx\t1।04 (कालवर्गः)\n"
    "1।05।01\tबुद्धिर्मनीषा धिषणा। धीः प्रज्ञा शेमुषी मतिः॥\tx\t1।05 (धीवर्गः)\n"
    "१।५।२\tधीर्धारणावती मेधा। <x> & y॥\tx\t1।05 (धीवर्गः)\n"
    "3।1।003\tसुकृती पुण्यवान्धन्यः॥\tx\t3।1 (TBD)\n"
)
WORDS_TSV = (
    "अर्थः\tप्रातिपदिकम्\tसंख्या\tअन्तर्संख्या\tलिङ्गम्\tवचनम्\tसुधा\tक्षीरस्वामी\tश्लोकः\n"
    "बुद्धिः\tमनीषा\t1।5।1\t1।2\tस्त्री०\t\tमन्यते।\t#N/A\tignored\n"
    "बुद्धिः\tबुद्धि\t1।05।01\t1।1\tस्त्री०\t\tबुध्यतेऽनया।\tबोधनम्।\tignored\n"
    "मनः\tचित्त\t1।04।31\t1।1\tनपुं०\t\t\t\tignored\n"
    "धारणावद्बुद्धिः\tमेधा\t1।05।02\t1।1\tस्त्री०\tबहु०\t<b>&\t\tignored\n"
    "बुद्धिः\tधी\t1।05।02\t1।2\tस्त्री०\t\t\t\tignored\n"
    "\tपुण्यवत्\t3।1।3\t1।1\tत्रि०\t\t\t\tignored\n"
)


def run_cli(*args):
    return subprocess.run([sys.executable, str(CONVERTER), *map(str, args)],
                          capture_output=True, text=True)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.shlokas = write(self.d / "shlokas.tsv", SHLOKAS_TSV)
        self.words = write(self.d / "words.tsv", WORDS_TSV)
        self.cfg = ak.load_config(ak.DEFAULT_CONFIG)

    def tearDown(self):
        self._tmp.cleanup()

    def convert(self, shlokas=None, words=None, **kw):
        cols = self.cfg["columns"]
        ph = self.cfg["placeholder_values"]
        conv = ak.Converter(self.cfg)
        text = conv.convert(ak.read_tsv(shlokas or self.shlokas, cols["shlokas"], ph),
                            ak.read_tsv(words or self.words, cols["words"], ph),
                            "shlokas.tsv", "words.tsv", **kw)
        return text, conv.warnings

    @staticmethod
    def records(text):
        """{first line of record: full record text}"""
        body = text.split("\n\n", 1)[1]
        recs = re.split(r"\n\n(?=- )", body.strip())
        return {r.split("\n", 1)[0]: r for r in recs}


class TestHelpers(unittest.TestCase):
    def test_parse_ref(self):
        self.assertEqual(ak.parse_ref("1।05।001", 3), (1, 5, 1))
        self.assertEqual(ak.parse_ref("१।५।१", 3), (1, 5, 1))
        self.assertEqual(ak.parse_ref("1।2"), (1, 2))
        self.assertIsNone(ak.parse_ref("1।2", 3))
        self.assertIsNone(ak.parse_ref("1।x।3", 3))
        self.assertIsNone(ak.parse_ref(""))

    def test_varga_name(self):
        self.assertEqual(ak.varga_name("1।05 (धीवर्गः)", []), "धीवर्गः")
        self.assertEqual(ak.varga_name("3।1 (TBD)", ["TBD"]), "")
        self.assertEqual(ak.varga_name("1।05", []), "")

    def test_format_verse(self):
        # '।।' (two dandas used as a double danda) is not split in the
        # middle, but does end the line.
        self.assertEqual(ak.format_verse("क ख। ग घ॥ ङ।। च"), ["क ख।", "ग घ॥", "ङ।।", "च"])
        self.assertEqual(ak.format_verse("<a> & b।"), ["&lt;a&gt; &amp; b।"])


class TestConfig(_Tmp):
    def test_default_config_loads(self):
        self.assertEqual(self.cfg["title"], "अमरकोषः")

    def test_bad_config(self):
        write(self.d / "c.yaml", "title: x\nid_format: '{0}'\ndisplay_format: '{0}'\n"
                                 "columns:\n  shlokas: {ref: a, varga: b}\n  words: {}\n")
        with self.assertRaises(DictionaryBuildError):
            ak.load_config(self.d / "c.yaml")

    def test_missing_column(self):
        write(self.d / "s.tsv", "संख्या\tश्लोकः\n1।1।1\tक॥\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            ak.read_tsv(self.d / "s.tsv", self.cfg["columns"]["shlokas"], [])
        self.assertIn("वर्गः", str(ctx.exception))
        self.assertEqual(ctx.exception.line, 1)

    def test_columns_by_header_and_placeholders(self):
        rows = ak.read_tsv(self.words, self.cfg["columns"]["words"], ["#N/A"])
        self.assertEqual(rows[0]["word"], "मनीषा")
        self.assertEqual(rows[0]["kshirasvami"], "")
        self.assertEqual(rows[0]["_line"], 2)


class TestConversion(_Tmp):
    def setUp(self):
        super().setUp()
        self.text, self.warnings = self.convert()
        self.recs = self.records(self.text)

    def test_header(self):
        self.assertTrue(self.text.startswith("HEADER:title=अमरकोषः\nHEADER:type=notes\n\n"))

    def test_record_keys(self):
        self.assertEqual(list(self.recs), [
            "- e:AK-1-04-031", "- e:AK-1-05-001", "- e:AK-1-05-002", "- e:AK-3-01-003",
            "- चित्त", "- बुद्धि", "- मनीषा", "- मेधा", "- धी", "- पुण्यवत्"])
        self.assertEqual(self.warnings, [])

    def test_verse_record(self):
        rec = self.recs["- e:AK-1-05-001"]
        lines = rec.split("\n")
        self.assertEqual(lines[1:4], ["१।५।१", "बुद्धिर्मनीषा धिषणा।", "धीः प्रज्ञा शेमुषी मतिः॥"])
        # words sorted by अन्तर्संख्या, linked, with lingam
        self.assertIn('• <b>अर्थः</b> – बुद्धिः ⇒ <a href="bword://buddhi">बुद्धि</a>(स्त्री०), '
                      '<a href="bword://maniiShaa">मनीषा</a>(स्त्री०)', rec)
        self.assertIn('Prev:<a href="bword://AK-1-04-031">१।४।३१</a>, '
                      'Next:<a href="bword://AK-1-05-002">१।५।२</a>', rec)

    def test_first_and_last_verse_nav(self):
        self.assertNotIn("Prev:", self.recs["- e:AK-1-04-031"])
        self.assertNotIn("Next:", self.recs["- e:AK-3-01-003"])

    def test_verse_with_meaningless_word(self):
        self.assertIn('• <a href="bword://puNyavat">पुण्यवत्</a>(त्रि०)', self.recs["- e:AK-3-01-003"])

    def test_word_record(self):
        rec = self.recs["- बुद्धि"]
        self.assertIn("• <b>अर्थः</b> – बुद्धिः", rec)
        self.assertIn("• <b>लिङ्गम्</b> – स्त्री०", rec)
        self.assertIn("• <b>सुधा</b> – बुध्यतेऽनया।", rec)
        self.assertIn("• <b>क्षीरस्वामी</b> – बोधनम्।", rec)
        # synonyms across verses, in reference order, excluding itself
        self.assertIn('• <b>समानार्थकाः</b> – <a href="bword://maniiShaa">मनीषा</a>(स्त्री०), '
                      '<a href="bword://dhii">धी</a>(स्त्री०)', rec)
        self.assertIn('• <a href="bword://AK-1-05-001">१।५।१</a> [धीवर्गः]', rec)

    def test_word_defaults_escaping_and_empty_fields(self):
        self.assertIn("• <b>क्षीरस्वामी</b> – ॥*॥", self.recs["- मनीषा"])  # #N/A -> default
        medha = self.recs["- मेधा"]
        self.assertIn("• <b>लिङ्गम्</b> – स्त्री० [बहु०]", medha)
        self.assertIn("• <b>सुधा</b> – &lt;b&gt;&amp;", medha)
        self.assertIn("&lt;x&gt; &amp; y॥", medha)
        self.assertNotIn("समानार्थकाः", medha)
        punya = self.recs["- पुण्यवत्"]
        self.assertNotIn("अर्थः", punya)
        self.assertNotIn("सुधा", punya)
        self.assertIn('[', self.recs["- चित्त"])  # कालवर्गः shown
        self.assertNotIn("TBD", punya)

    def test_all_links_resolve_after_build(self):
        """The real check: build the output and compare links with keys."""
        import createDictionary
        book = self.d / "book"
        write(book / "meta.yaml", "name: AK\n")
        write(book / "ak.txt", self.text)
        out, _ = createDictionary.build_book(book, "tabfile", False, 0, stats_file=None)
        keys, links = set(), set()
        for line in filter(None, out.split("\n")):
            k, body = line.split("\t", 1)
            keys |= set(k.split("|"))
            links |= set(re.findall(r'bword://([^"]+)"', body))
        self.assertEqual(len(keys), 10)
        self.assertEqual(links - keys, set())


class TestProblems(_Tmp):
    def test_missing_verse_strict_and_lax(self):
        words = write(self.d / "w.tsv", WORDS_TSV + "अ\tकिम्\t2।1।1\t1।1\t\t\t\t\t\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(words=words)
        self.assertIn("words.tsv:8", str(ctx.exception))
        text, warnings = self.convert(words=words, lax=True)
        self.assertTrue(any("2।1।1" in w for w in warnings))
        self.assertIn("- किम्", text)

    def test_duplicate_verse(self):
        s = write(self.d / "s.tsv", SHLOKAS_TSV + "1।5।1\tदुप॥\t\t1।05\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(shlokas=s)
        self.assertIn("duplicate", str(ctx.exception))
        self.assertEqual(ctx.exception.line, 6)

    def test_bad_reference(self):
        s = write(self.d / "s.tsv", SHLOKAS_TSV + "1।5\tक॥\t\t1।05\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(shlokas=s)
        self.assertEqual(ctx.exception.line, 6)

    def test_bad_headword(self):
        w = write(self.d / "w.tsv", WORDS_TSV + "अ\tक;ख\t1।5।1\t1।3\t\t\t\t\t\n")
        with self.assertRaises(DictionaryBuildError):
            self.convert(words=w)

    def test_line_starting_with_dash(self):
        s = write(self.d / "s.tsv", SHLOKAS_TSV.replace("सुकृती", "-सुकृती"))
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(shlokas=s)
        self.assertIn("starting with '-'", str(ctx.exception))

    def test_empty_headword_warns(self):
        w = write(self.d / "w.tsv", WORDS_TSV + "अ\t\t1।5।1\t1।3\t\t\t\t\t\n")
        _, warnings = self.convert(words=w)
        self.assertTrue(any("no headword" in x for x in warnings))


class TestCli(_Tmp):
    def test_full_run(self):
        out = self.d / "out" / "ak.txt"
        res = run_cli("--words", self.words, "--shlokas", self.shlokas, "--output", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("- e:AK-1-05-001", out.read_text(encoding="utf-8"))

    def test_varga_needs_debug(self):
        res = run_cli("--words", self.words, "--shlokas", self.shlokas,
                      "--output", self.d / "o.txt", "--varga", "1।05")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--debug", res.stderr)

    def test_debug_varga(self):
        out = self.d / "o.txt"
        res = run_cli("--words", self.words, "--shlokas", self.shlokas,
                      "--output", out, "--debug", "--varga", "1।05")
        self.assertEqual(res.returncode, 0, res.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn("- e:AK-1-05-002", text)
        self.assertNotIn("- e:AK-1-04-031", text)
        self.assertNotIn("- चित्त", text)
        # neighbours outside the varga are reported, not fatal
        self.assertIn("AK-1-04-031", res.stderr)

    def test_data_error_exit_code(self):
        s = write(self.d / "s.tsv", "संख्या\tश्लोकः\n")
        res = run_cli("--words", self.words, "--shlokas", s, "--output", self.d / "o.txt")
        self.assertEqual(res.returncode, 2)
        self.assertIn("s.tsv:1", res.stderr)
        self.assertFalse((self.d / "o.txt").exists())


if __name__ == "__main__":
    unittest.main()
