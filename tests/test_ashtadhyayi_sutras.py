"""Tests for scripts/converters/ashtadhyayi_sutras.py (synthetic data in
the shape of https://github.com/ashtadhyayi-com/data sutraani/)."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SCRIPTS_DIR, write

sys.path.insert(0, str(SCRIPTS_DIR / "converters"))
import ashtadhyayi_sutras as su  # noqa: E402
from ashtadhyayi_common import load_config  # noqa: E402
from errors import DictionaryBuildError  # noqa: E402

CONVERTER = SCRIPTS_DIR / "converters" / "ashtadhyayi_sutras.py"


def sutra(i, a, p, n, s, pc="", typ="V$$", an="", ss="", skn="0"):
    return {"i": i, "a": str(a), "p": str(p), "n": str(n), "s": s, "pc": pc, "type": typ,
            "an": an, "ss": ss, "skn": skn}


BASE = {"name": "sutraani", "data": [
    sutra("11062", 1, 1, 62, "प्रत्ययलोपे प्रत्ययलक्षणम्", skn="262"),
    sutra("11063", 1, 1, 63, "न लुमताङ्गस्य",
          pc="न$S$0$0$##लुमता$S$3$1$##अङ्गस्य$S$6$1$##भवति$T$$$##x$S$$$",
          typ="P$प्रत्ययलक्षणपरिभाषा$##AT$आद्यन्तवदतिदेशः$",
          an="प्रत्ययलोपे$11062##प्रत्ययलक्षणम्$11062", ss="लुमता लुप्ते न", skn="263"),
    sutra("11001", 1, 1, 1, "वृद्धिरादैच्", pc="वृद्धिः$S$1$1$##आत्-ऐच्$S$1$1$",
          typ="S$वृद्धिसंज्ञा$##S$ऐच्संज्ञा$"),
    sutra("34002", 3, 4, 2, "क्रियासमभिहारे लोट्; लोटो हिस्वौ"),
    sutra("83037", 8, 3, 37, "कुप्वोः ≍क≍पौ च"),
]}

SUTRARTHA = {
    "11063": {"sa": "लुक् - <b>लोपः</b> न ।",
              "sd": "<title>शीर्षकम्</title>\nदृष्टव्यम् <<प्रत्ययलोपे प्रत्ययलक्षणम्>> [[1.1.62]] ।\n"
                    "-> क्रमः <qt>राम:</qt>\n<li>एकम्<li>द्वे\nअज्ञातम् [[9.9.9]] <weird>x</weird> a<b & **c"},
    "11001": {"sa": "", "sd": ""},
    "11062": {"sa": "", "sd": "केवलम् विस्तरः"},
}
KASHIKA = {
    "11001": "प्रदेशाः — <<सिचि>> [[१.१.६३]] इति। केवलम् [[1.1.062]]॥",
    "11063": "",
}
KAUMUDI = {
    "11063": "<<हलन्त्यम्>> <{SK262}> । <{SK263}> <<नादिचि १.१.६२>> {$ {!1290 ओलजी!} व्रीडायाम्$}\tअथ <{उ5}> <{SK999}>",
}
VASU = {"11062": "Of the base [[1.1.63]] <i>sutra</i>.\n- Nominative"}

SUTRA_KEYS = "- १.१.०६३;न लुमताङ्गस्य;प्रत्ययलक्षणपरिभाषा;लुमता;अङ्गस्य;भवति;x"


class _Data(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.data = self.d / "sutraani"
        for name, obj in [("data.txt", BASE), ("sutrartha.txt", SUTRARTHA),
                          ("kashika.txt", KASHIKA), ("kaumudi.txt", KAUMUDI),
                          ("vasu_english.txt", VASU)]:
            write(self.data / name, json.dumps(obj, ensure_ascii=False))
        self.cfg = load_config(su.DEFAULT_CONFIG, su.REQUIRED_CONFIG)
        self.parts, self.warnings = su.convert(self.data, self.cfg)

    def tearDown(self):
        self._tmp.cleanup()

    def records(self, part, parts=None):
        """{keys line: [body lines]}"""
        body = (parts or self.parts)[part].split("\n\n", 1)[1]
        out = {}
        for rec in re.split(r"\n(?=- )", body.strip()):
            lines = rec.strip("\n").split("\n")
            out[lines[0]] = lines[1:]
        return out


class TestSutraPart(_Data):
    def test_header_and_order(self):
        text = self.parts["sutra"]
        self.assertTrue(text.startswith("HEADER:title=अष्टाध्यायी\nHEADER:type=notes\n"))
        nums = re.findall(r"^- ([^;\n]+)", text, re.M)
        self.assertEqual(nums, ["१.१.००१", "१.१.०६२", "१.१.०६३", "३.४.००२", "८.३.०३७"])

    def test_keys(self):
        recs = self.records("sutra")
        # number, sutra, saṃjñā/paribhāṣā names (not AT), declined words
        # (not the avyaya न); tiṅanta and no-vibhakti words are kept.
        self.assertIn(SUTRA_KEYS, recs)
        self.assertIn("- १.१.००१;वृद्धिरादैच्;वृद्धिसंज्ञा;ऐच्संज्ञा;वृद्धिः;आत्-ऐच्", recs)
        # ';' in a sutra splits into keys; unmappable characters are
        # dropped from keys only.
        self.assertIn("- ३.४.००२;क्रियासमभिहारे लोट्;लोटो हिस्वौ", recs)
        self.assertIn("- ८.३.०३७;कुप्वोः कपौ च", recs)
        self.assertIn("<b>८.३.०३७ कुप्वोः ≍क≍पौ च ।</b>", recs["- ८.३.०३७;कुप्वोः कपौ च"])
        self.assertTrue(any("'≍'" in w and "2 key" in w for w in self.warnings))

    def test_entry(self):
        self.assertEqual(self.records("sutra")[SUTRA_KEYS], [
            "<b>१.१.०६३ न लुमताङ्गस्य ।</b>",
            "न (अ०) लुमता (३।१) अङ्गस्य (६।१) भवति x",
            'अनुवृत्तिः – <a href="bword://1.1.062">प्रत्ययलोपे</a> '
            '<a href="bword://1.1.062">प्रत्ययलक्षणम्</a>',
            "लुमता लुप्ते न"])          # no sutrārtha here: that's the 'artha' part

    def test_empty_parts_omitted(self):
        body = self.records("sutra")["- १.१.००१;वृद्धिरादैच्;वृद्धिसंज्ञा;ऐच्संज्ञा;वृद्धिः;आत्-ऐच्"]
        self.assertEqual(body, ["<b>१.१.००१ वृद्धिरादैच् ।</b>", "वृद्धिः (१।१) आत्-ऐच् (१।१)"])


class TestPadacchedaKeys(_Data):
    def keys_line(self, mode):
        parts, _ = su.convert(self.data, dict(self.cfg, padaccheda_keys=mode), wanted={"sutra"})
        return next(l for l in parts["sutra"].split("\n") if l.startswith("- १.१.०६३;"))

    def test_modes(self):
        base = "- १.१.०६३;न लुमताङ्गस्य;प्रत्ययलक्षणपरिभाषा"
        self.assertEqual(self.keys_line("none"), base)
        self.assertEqual(self.keys_line("declined"), base + ";लुमता;अङ्गस्य;भवति;x")
        # 'all' adds the avyaya न as well
        self.assertEqual(self.keys_line("all"), base + ";न;लुमता;अङ्गस्य;भवति;x")

    def test_bad_mode(self):
        with self.assertRaises(DictionaryBuildError):
            su.convert(self.data, dict(self.cfg, padaccheda_keys="some"))


class TestArthaPart(_Data):
    def test_entries(self):
        recs = self.records("artha")
        # sutras with an empty sutrārtha (1.1.1) or none get no entry
        self.assertEqual(list(recs), ["- १.१.०६२;प्रत्ययलोपे प्रत्ययलक्षणम्",
                                      "- १.१.०६३;न लुमताङ्गस्य"])
        self.assertTrue(self.parts["artha"].startswith("HEADER:title=सूत्रार्थः\n"))
        self.assertEqual(recs["- १.१.०६२;प्रत्ययलोपे प्रत्ययलक्षणम्"],
                         ["<b>१.१.०६२ प्रत्ययलोपे प्रत्ययलक्षणम् । (सूत्रार्थः)</b>",
                          "केवलम् विस्तरः"])               # 'sd' only, no bold line

    def test_rendering(self):
        body = self.records("artha")["- १.१.०६३;न लुमताङ्गस्य"]
        self.assertEqual(body[:2], ["<b>१.१.०६३ न लुमताङ्गस्य । (सूत्रार्थः)</b>",
                                    "<b>लुक् - <b>लोपः</b> न ।</b>"])
        rest = "\n".join(body[2:])
        self.assertIn("<b>शीर्षकम्</b>", rest)
        self.assertIn('<a href="bword://1.1.062">प्रत्ययलोपे प्रत्ययलक्षणम्</a> [1.1.62]', rest)
        self.assertIn("&#45;&gt; क्रमः <i>राम:</i>", rest)      # no '-' line start
        self.assertIn("• एकम्\n• द्वे", rest)
        self.assertIn("अज्ञातम् [9.9.9] x a&lt;b &amp; &#42;&#42;c", rest)
        self.assertIn("artha: 1 sutra reference(s) not resolved, left as text", self.warnings)


class TestCommentaries(_Data):
    def test_kashika(self):
        recs = self.records("kashika")
        self.assertEqual(list(recs), ["- १.१.००१;वृद्धिरादैच्"])    # empty text: no entry
        self.assertEqual(recs["- १.१.००१;वृद्धिरादैच्"], [
            "<b>१.१.००१ वृद्धिरादैच् । (काशिका)</b>",
            'प्रदेशाः — <a href="bword://1.1.063">सिचि</a> [१.१.६३] इति। केवलम् '
            '<a href="bword://1.1.062">[1.1.062]</a>॥'])
        self.assertTrue(self.parts["kashika"].startswith("HEADER:title=काशिका\n"))

    def test_kaumudi(self):
        body = self.records("kaumudi")["- १.१.०६३;न लुमताङ्गस्य"]
        self.assertEqual(body[0], "<b>१.१.०६३ न लुमताङ्गस्य । (कौमुदी)</b>")
        self.assertEqual(body[1], '<a href="bword://1.1.062">हलन्त्यम्</a> [SK262] । '
                                  '<a href="bword://1.1.063">[SK263]</a> '
                                  '<a href="bword://1.1.062">नादिचि</a> [१.१.६२] '
                                  '<b>ओलजी व्रीडायाम्</b>')
        self.assertEqual(body[2], "अथ [उ5] [SK999]")      # tab -> new line
        self.assertIn("kaumudi: 1 sutra reference(s) not resolved, left as text", self.warnings)

    def test_vasu(self):
        body = self.records("vasu")["- १.१.०६२;प्रत्ययलोपे प्रत्ययलक्षणम्"]
        self.assertEqual(body, ["<b>१.१.०६२ प्रत्ययलोपे प्रत्ययलक्षणम् । (Vasu)</b>",
                                'Of the base <a href="bword://1.1.063">[1.1.63]</a> <i>sutra</i>.',
                                "&#45; Nominative"])


class TestBuild(_Data):
    def test_all_links_resolve_after_build(self):
        """Build every part with the real pipeline; links must hit keys."""
        import createDictionary
        keys, links = set(), set()
        for part, text in self.parts.items():
            book = self.d / "books" / part
            write(book / "meta.yaml", f"name: {part}\n")
            write(book / f"{part}.txt", text)
            out, _ = createDictionary.build_book(book, "tabfile", False, 0, stats_file=None)
            for line in filter(None, out.split("\n")):
                k, body = line.split("\t", 1)
                keys |= set(k.split("|"))
                links |= set(re.findall(r'bword://([^"]+)"', body))
        self.assertIn("1.1.063", keys)
        self.assertEqual(links - keys, set())


class TestCli(_Data):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CONVERTER), *map(str, args)],
                              capture_output=True, text=True)

    def test_parts(self):
        out = self.d / "out"
        res = self.run_cli("--data", self.data, "--output-dir", out, "--parts", "sutra,vasu")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["sutra.txt", "vasu.txt"])

    def test_errors(self):
        res = self.run_cli("--data", self.data, "--output-dir", self.d / "o", "--parts", "nosuch")
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown part", res.stderr)
        write(self.data / "kashika.txt", "{bad json")
        res = self.run_cli("--data", self.data, "--output-dir", self.d / "o")
        self.assertEqual(res.returncode, 2)
        self.assertIn("kashika.txt:1: invalid JSON", res.stderr)


if __name__ == "__main__":
    unittest.main()
