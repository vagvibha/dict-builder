"""Tests for scripts/converters/amarakosha_to_notes.py."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SCRIPTS_DIR, write
from errors import DictionaryBuildError

sys.path.insert(0, str(SCRIPTS_DIR / "converters"))
import amarakosha_to_notes as ak  # noqa: E402

CONVERTER = SCRIPTS_DIR / "converters" / "amarakosha_to_notes.py"

# Columns deliberately in a different order from the real data, with
# extra columns, mixed zero-padding, '।' and Devanagari digits in references.
SHLOKAS_CSV = (
    "संख्या,श्लोकः,extra\n"
    "1.04.31,चित्तं तु चेतो हृदयं। स्वान्तं हृन्मानसं मनः॥,x\n"
    "1.05.01,बुद्धिर्मनीषा धिषणा। धीः प्रज्ञा शेमुषी मतिः॥,x\n"
    "१।५।२,धीर्धारणावती मेधा। <x> & y॥,x\n"
    "3.1.003,सुकृती पुण्यवान्धन्यः॥,x\n"
)
WORDS_CSV = (
    "अर्थः,प्रातिपदिकम्,संख्या,अन्तर्संख्या,लिङ्गम्,वचनम्,sudha_id,ks_id,dup_of,issues\n"
    "बुद्धिः,मनीषा,1.5.1,1.2,स्त्री०,,s2,k2,,\n"
    'बुद्धिः,बुद्धि,1.05.01,1.1,स्त्री०,,s1,"k1, k3",,ignored\n'
    "मनः,चित्त,1.04.31,1.1,नपुं०,,,,,\n"
    "धारणावद्बुद्धिः,मेधा,1.05.02,1.1,स्त्री०,बहु०,s3,,,\n"
    "बुद्धिः,धी,1.05.02,1.2,स्त्री०,,,,x,\n"
    ",पुण्यवत्,3.1.3,1.1,त्रि०,,s4,,,\n"
)
SUDHA_CSV = (
    "sudha_id,संख्या,commentary,,\n"
    "s1,1.05.001,बुध्यतेऽनया।,,\n"
    "s2,1.05.001,मन्यते।,,\n"
    "s3,1.05.002,<b>&,,\n"
    "s4,3.01.003,,,\n"
    "unused,1.01.001,x,,\n"
)
KS_CSV = (
    "ks_id,वर्गः,varga_name,commentary\n"
    "k1,1.05,धीवर्गः,बोधनम्।\n"
    "k2,1.05,धीवर्गः,#N/A\n"
    "k3,1.05,धीवर्गः,द्वितीयम्।\n"
)
VARGAS_CSV = "वर्गः,varga_name\n1.04,कालवर्गः\n1.05,धीवर्गः\n3.01,TBD\n"
FILES = {"shlokas": SHLOKAS_CSV, "words": WORDS_CSV, "sudha": SUDHA_CSV,
         "kshirasvami": KS_CSV, "vargas": VARGAS_CSV}


def write_data(d: Path, **override) -> Path:
    """Writes the five CSVs under their default names into d."""
    for table, text in {**FILES, **override}.items():
        write(d / ak.DEFAULT_FILES[table], text)
    return d


def run_cli(*args):
    return subprocess.run([sys.executable, str(CONVERTER), *map(str, args)],
                          capture_output=True, text=True)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.data = write_data(self.d / "data")
        self.cfg = ak.load_config(ak.DEFAULT_CONFIG)

    def tearDown(self):
        self._tmp.cleanup()

    def convert(self, lax=False, only_varga=None, **override):
        """override: table -> replacement CSV text."""
        data = write_data(self.d / "override", **override) if override else self.data
        cols, ph = self.cfg["columns"], self.cfg["placeholder_values"]
        files = {t: data / name for t, name in ak.DEFAULT_FILES.items()}
        tables = {t: ak.read_table(f, cols[t], ph) for t, f in files.items()}
        conv = ak.Converter(self.cfg)
        text = conv.convert(tables, {t: f.name for t, f in files.items()},
                            only_varga=only_varga, lax=lax)
        return text, conv.warnings

    @staticmethod
    def records(text):
        """{first line of record: full record text}"""
        body = text.split("\n\n", 1)[1]
        recs = re.split(r"\n\n(?=- )", body.strip())
        return {r.split("\n", 1)[0]: r for r in recs}


class TestHelpers(unittest.TestCase):
    def test_parse_ref(self):
        self.assertEqual(ak.parse_ref("1.05.001", 3), (1, 5, 1))
        self.assertEqual(ak.parse_ref("1।05।001", 3), (1, 5, 1))
        self.assertEqual(ak.parse_ref("१।५।१", 3), (1, 5, 1))
        self.assertEqual(ak.parse_ref("1।2"), (1, 2))
        self.assertIsNone(ak.parse_ref("1।2", 3))
        self.assertIsNone(ak.parse_ref("1।x।3", 3))
        self.assertIsNone(ak.parse_ref(""))

    def test_split_ids(self):
        self.assertEqual(ak.split_ids("1.04.15#2, 1.04.15#3"), ["1.04.15#2", "1.04.15#3"])
        self.assertEqual(ak.split_ids(" a ;b,"), ["a", "b"])
        self.assertEqual(ak.split_ids(""), [])

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
        write(self.d / "s.csv", "संख्या,text\n1.1.1,क॥\n")
        with self.assertRaises(DictionaryBuildError) as ctx:
            ak.read_table(self.d / "s.csv", self.cfg["columns"]["shlokas"], [])
        self.assertIn("श्लोकः", str(ctx.exception))
        self.assertEqual(ctx.exception.line, 1)

    def test_columns_by_header_and_placeholders(self):
        rows = ak.read_table(self.data / "words.csv", self.cfg["columns"]["words"], [])
        self.assertEqual(rows[1]["word"], "बुद्धि")
        self.assertEqual(rows[1]["kshirasvami"], "k1, k3")
        self.assertEqual(rows[1]["_line"], 3)
        ks = ak.read_table(self.data / "ks_words.csv", self.cfg["columns"]["kshirasvami"], ["#N/A"])
        self.assertEqual(ks[1], {"_line": 3, "id": "k2", "text": ""})


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
        # two ks ids -> both commentaries, in the order listed
        self.assertIn("• <b>क्षीरस्वामी</b> – बोधनम्।<br>द्वितीयम्।", rec)
        # synonyms across verses, in reference order, excluding itself
        self.assertIn('• <b>समानार्थकाः</b> – <a href="bword://maniiShaa">मनीषा</a>(स्त्री०), '
                      '<a href="bword://dhii">धी</a>(स्त्री०)', rec)
        self.assertIn('• <a href="bword://AK-1-05-001">१।५।१</a> [धीवर्गः]', rec)

    def test_word_defaults_escaping_and_empty_fields(self):
        self.assertIn("• <b>क्षीरस्वामी</b> – ॥*॥", self.recs["- मनीषा"])  # #N/A -> default
        self.assertIn("• <b>क्षीरस्वामी</b> – ॥*॥", self.recs["- चित्त"])   # no ks_id
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
        words = WORDS_CSV + "अ,किम्,2.1.1,1.1,,,,,,\n"
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(words=words)
        self.assertIn("words.csv:8", str(ctx.exception))
        text, warnings = self.convert(words=words, lax=True)
        self.assertTrue(any("2.1.1" in w for w in warnings))
        self.assertIn("- किम्", text)

    def test_missing_commentary_id(self):
        words = WORDS_CSV.replace(",s3,", ",s9,")
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(words=words)
        self.assertIn("sudha id 's9' of 'मेधा' is not in sudha.csv", str(ctx.exception))
        _, warnings = self.convert(words=words, lax=True)
        self.assertEqual(len(warnings), 1)

    def test_missing_varga(self):
        vargas = VARGAS_CSV.replace("1.04,कालवर्गः\n", "")
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(vargas=vargas)
        self.assertIn("varga 1.4 is not in vargas.csv", str(ctx.exception))

    def test_duplicates(self):
        cases = {
            "verse": ("shlokas", SHLOKAS_CSV + "1.5.1,दुप॥,\n", 6),
            "sudha id": ("sudha", SUDHA_CSV + "s1,x,y,,\n", 7),
            "varga": ("vargas", VARGAS_CSV + "1.05,x\n", 5),
        }
        for label, (table, text, line) in cases.items():
            with self.subTest(label):
                with self.assertRaises(DictionaryBuildError) as ctx:
                    self.convert(**{table: text})
                self.assertIn("duplicate", str(ctx.exception))
                self.assertEqual(ctx.exception.line, line)

    def test_bad_reference(self):
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(shlokas=SHLOKAS_CSV + "1.5,क॥,\n")
        self.assertEqual(ctx.exception.line, 6)

    def test_bad_headword(self):
        with self.assertRaises(DictionaryBuildError):
            self.convert(words=WORDS_CSV + 'अ,"क;ख",1.5.1,1.3,,,,,,\n')

    def test_line_starting_with_dash(self):
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.convert(shlokas=SHLOKAS_CSV.replace("सुकृती", "-सुकृती"))
        self.assertIn("starting with '-'", str(ctx.exception))

    def test_empty_headword_warns(self):
        _, warnings = self.convert(words=WORDS_CSV + "अ,,1.5.1,1.3,,,,,,\n")
        self.assertTrue(any("no headword" in x for x in warnings))


class TestCli(_Tmp):
    def test_full_run(self):
        out = self.d / "out" / "ak.txt"
        res = run_cli("--data", self.data, "--output", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("- e:AK-1-05-001", out.read_text(encoding="utf-8"))

    def test_single_file_override(self):
        write(self.d / "v.csv", VARGAS_CSV.replace("धीवर्गः", "बुद्धिवर्गः"))
        out = self.d / "o.txt"
        res = run_cli("--data", self.data, "--vargas", self.d / "v.csv", "--output", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("[बुद्धिवर्गः]", out.read_text(encoding="utf-8"))

    def test_needs_data_or_files(self):
        res = run_cli("--words", self.data / "words.csv", "--output", self.d / "o.txt")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--data", res.stderr)

    def test_varga_needs_debug(self):
        res = run_cli("--data", self.data, "--output", self.d / "o.txt", "--varga", "1.05")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--debug", res.stderr)

    def test_debug_varga(self):
        out = self.d / "o.txt"
        res = run_cli("--data", self.data, "--output", out, "--debug", "--varga", "1.05")
        self.assertEqual(res.returncode, 0, res.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn("- e:AK-1-05-002", text)
        self.assertNotIn("- e:AK-1-04-031", text)
        self.assertNotIn("- चित्त", text)
        # neighbours outside the varga are reported, not fatal
        self.assertIn("AK-1-04-031", res.stderr)

    def test_data_error_exit_code(self):
        write(self.data / "shlokas.csv", "संख्या,श्लोकः\n1.1.1,क॥\n")   # varga 1.01 missing
        write(self.d / "s.csv", "संख्या\n")
        res = run_cli("--data", self.data, "--shlokas", self.d / "s.csv",
                      "--output", self.d / "o.txt")
        self.assertEqual(res.returncode, 2)
        self.assertIn("s.csv:1", res.stderr)
        self.assertFalse((self.d / "o.txt").exists())


if __name__ == "__main__":
    unittest.main()
