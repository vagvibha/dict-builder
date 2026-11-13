"""Tests for scripts/converters/ashtadhyayi_dhatus.py (synthetic data in
the shape of https://github.com/ashtadhyayi-com/data dhatu/)."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SCRIPTS_DIR, write

sys.path.insert(0, str(SCRIPTS_DIR / "converters"))
import ashtadhyayi_dhatus as dh  # noqa: E402
from ashtadhyayi_common import load_config  # noqa: E402

CONVERTER = SCRIPTS_DIR / "converters" / "ashtadhyayi_dhatus.py"


def dhatu(bi, d, aup, gana, pada="P", settva="S", karma="S", artha="", hindi="",
          ups=(), antar=""):
    return {"baseindex": bi, "dhatu": d, "aupadeshik": aup, "gana": gana, "pada": pada,
            "settva": settva, "karma": karma, "artha": artha, "artha_hindi": hindi,
            "upasargas": [{"name": n, "artha_hindi": h} for n, h in ups],
            "antarganas": antar}


BASE = {"name": "dhatu", "data": [
    dhatu("08.0010", "कृ", "डुकृञ्", "8", "U", "A", "S", "करणे", "करना",
          ups=[("प्र", "आरम्भ करना"), ("सम् + आ", "x"), ("उप", "उपकार करना"), ("उप", "बदलना")],
          antar="भिदादिः"),
    dhatu("05.0007", "कृ", "कृञ्", "5", "U", "A", "S", "हिंसायाम्"),
    dhatu("01.0049", "सिध्", "षिधँ", "1", artha="गत्याम्", ups=[("नि", "रोकना")]),
    dhatu("01.0050", "सिध्", "षिधूँ", "1", artha="शास्त्रे"),
    dhatu("04.0089", "सिध्", "षिधुँ", "4", karma="A", artha="संराद्धौ"),
    dhatu("01.0002", "एध्", "एधँ", "1", "A", "S", "A", "वृद्धौ"),
    dhatu("01.0933", "घटादयो मितः", "-", "1", "-", "-", "-"),          # gaṇasūtra
]}

KRT = {
    "08.0010": {"क्त": "कृत,कृतः,कृता,कृतम्", "अच्": "कर,करः,करा,करम्", "क्त्वा": "कृत्वा,,,",
                "शतृ": "कुर्वत्,कुर्वन्,कुर्वती,कुर्वत्/कुर्वद्", "ल्युट्": "करण,,,करणम्",
                "नवीन": "नव,,,"},
    "01.0002": {"क्त": "एधित,एधितः,एधिता,एधितम्"},
    "99.9999": {"क्त": "x,,,"},
}
KARTARI = {
    "08.0010": {"plat": "करोति;कुरुतः;कुर्वन्ति;करोषि;कुरुथः;कुरुथ;करोमि;कुर्वः;कुर्मः",
                "alat": "कुरुते;कुर्वाते;कुर्वते;कुरुषे;कुर्वाथे;कुरुध्वे;कुर्वे;कुर्वहे;कुर्महे",
                "plot": "करोतु,कुरुतात्;कुरुताम्;कुर्वन्तु;कुरु;कुरुतम्;कुरुत;करवाणि;करवाव;करवाम"},
    "01.0002": {"alit": ";".join(f"a{i},b{i}" for i in range(1, 10)).replace("a", "एधाञ्चक्रे")
                .replace("b", "एधामास")},
}


class _Data(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.data = self.d / "dhatu"
        self.cfg = load_config(dh.DEFAULT_CONFIG, dh.REQUIRED_CONFIG)
        files = {"data.txt": BASE}
        for part, p in self.cfg["parts"].items():
            files[p["file"]] = {"krt": KRT, "lakara": KARTARI}[p["kind"]]
        for name, obj in files.items():
            write(self.data / name, json.dumps(obj, ensure_ascii=False))
        self.parts, self.warnings = dh.convert(self.data, self.cfg)

    def tearDown(self):
        self._tmp.cleanup()

    def records(self, part):
        """{keys line: [body lines]} (records with the same keys line are
        returned as a list of bodies under that line)"""
        body = self.parts[part].split("\n\n", 1)[1]
        out = {}
        for rec in re.split(r"\n(?=- )", body.strip()):
            lines = rec.strip("\n").split("\n")
            out.setdefault(lines[0], []).append(lines[1:])
        return {k: v[0] if len(v) == 1 else v for k, v in out.items()}


class TestSandhi(unittest.TestCase):
    CASES = [
        (["प्र"], "इ", "इण्", "प्रे"), (["अभि"], "अस्", "असँ", "अभ्यस्"),
        (["अनु"], "इ", "इण्", "अन्वि"), (["प्र"], "ऋच्छ्", "ऋछँ", "प्रार्च्छ्"),
        (["प्र"], "एज्", "एजृँ", "प्रेज्"), (["उप"], "उष्", "उषँ", "उपोष्"),
        (["सम्"], "गम्", "गमॢँ", "संगम्"), (["सम्"], "इ", "इण्", "समि"),
        (["उद्"], "गम्", "गमॢँ", "उद्गम्"), (["उद्"], "नी", "णीञ्", "उन्नी"),
        (["उद्"], "हृ", "हृञ्", "उद्धृ"), (["उद्"], "श्वस्", "श्वसँ", "उच्छ्वस्"),
        (["उद्"], "स्था", "ष्ठा", "उत्था"), (["उद्"], "चर्", "चरँ", "उच्चर्"),
        (["उद्"], "तॄ", "तॄ", "उत्तॄ"),
        (["निर्"], "गम्", "गमॢँ", "निर्गम्"), (["निर्"], "कृ", "डुकृञ्", "निष्कृ"),
        (["निस्"], "सृ", "सृ", "निःसृ"), (["निर्"], "आ", "", "निरा"),
        (["निर्"], "रस्", "", "नीरस्"),
        (["प्र"], "नम्", "णमँ", "प्रणम्"), (["परि"], "नी", "णीञ्", "परिणी"),
        (["प्र"], "नद्", "नदँ", "प्रनद्"),            # नोपदेश: no णत्व
        (["नि"], "सिध्", "षिधँ", "निषिध्"), (["अधि"], "स्था", "ष्ठा", "अधिष्ठा"),
        (["आ"], "इ", "इण्", "ए"), (["सम्", "आ"], "कृ", "डुकृञ्", "समाकृ"),
        (["वि", "आ"], "कृ", "डुकृञ्", "व्याकृ"), (["प्रति", "उप"], "कृ", "डुकृञ्", "प्रत्युपकृ"),
        (["अभि", "वि", "आ"], "हृ", "हृञ्", "अभिव्याहृ"),
    ]

    def test_cases(self):
        for ups, d, aup, expected in self.CASES:
            with self.subTest(ups=ups, dhatu=d):
                self.assertEqual(dh.upasarga_sandhi(ups, d, aup), expected)

    def test_phoneme_roundtrip(self):
        for w in ["डुकृञ्", "क्षिप्", "घसॢँ", "संस्कृ", "एधँ", "अं", "निःसृ"]:
            self.assertEqual(dh.from_phonemes(dh.to_phonemes(w)), w)


class TestDhatuPart(_Data):
    def test_disambiguation(self):
        recs = self.records("dhatu")
        heads = [k for k in recs if k.startswith("- ") and "धातु" in k]
        self.assertEqual(heads, [
            "- एध्;एधँ;वृद्धौ;एध्-धातु",
            "- सिध्;षिधँ;गत्याम्;सिध्-धातु;सिध्-१.४९-धातु",     # same gaṇa: gaṇa.number
            "- सिध्;षिधूँ;शास्त्रे;सिध्-धातु;सिध्-१.५०-धातु",
            "- सिध्;षिधुँ;संराद्धौ;सिध्-धातु;सिध्-४-धातु",      # unique in its gaṇa
            "- कृ;कृञ्;हिंसायाम्;कृ-धातु;कृ-५-धातु",
            "- कृ;डुकृञ्;करणे;कृ-धातु;कृ-८-धातु",
        ])   # sorted by baseindex; the gaṇasūtra is skipped

    def test_dhatu_entry(self):
        body = self.records("dhatu")["- कृ;डुकृञ्;करणे;कृ-धातु;कृ-८-धातु"]
        self.assertEqual(body[:4], ["<b>डुकृञ् (कृ) करणे</b>",
                                    "तनादिः उभयपदी सकर्मकः अनिट् भिदादिः", "करना", ""])
        self.assertEqual(body[4], '• <a href="bword://kR-8-kRt">कृत्</a>, '
                                  '<a href="bword://kR-8-Nich-kRt">णिच्-कृत्</a>, '
                                  '<a href="bword://kR-8-san-kRt">सन्-कृत्</a>, '
                                  '<a href="bword://kR-8-yaN-kRt">यङ्-कृत्</a>, '
                                  '<a href="bword://kR-8-yaNluk-kRt">यङ्लुक्-कृत्</a>')
        self.assertTrue(body[5].startswith('• <a href="bword://kR-8-kartari">कर्तरि</a>, '
                                           '<a href="bword://kR-8-karmaNi">कर्मणि</a>, '))
        self.assertEqual(body[5].count("<a "), 10)
        # A dhatu with no forms in any part gets no links.
        self.assertEqual(len(self.records("dhatu")["- कृ;कृञ्;हिंसायाम्;कृ-धातु;कृ-५-धातु"]), 2)

    def test_upasarga_entries(self):
        recs = self.records("dhatu")
        self.assertEqual(recs["- प्रकृ"], ["आरम्भ करना", "",
                                          '<a href="bword://kR-8-dhaatu">डुकृञ् (कृ) करणे</a>',
                                          "तनादिः उभयपदी सकर्मकः अनिट् भिदादिः"])
        self.assertEqual(recs["- उपकृ"][:2], ["उपकार करना", "बदलना"])   # merged
        self.assertIn("- समाकृ", recs)
        self.assertIn("- निषिध्", recs)


class TestKrtPart(_Data):
    def test_entry(self):
        recs = self.records("shuddha-krdanta")
        key = ("- कृ-८-कृत्;कृत;कृतः;कृता;कृतम्;कृत्वा;कुर्वत्;कुर्वन्;कुर्वती;कुर्वद्;"
               "कर;करः;करा;करम्;करण;करणम्")
        self.assertEqual(list(recs), ["- एध्-कृत्;एधित;एधितः;एधिता;एधितम्", key])
        self.assertEqual(recs[key], [
            '<b><a href="bword://kR-8-dhaatu">डुकृञ् (कृ) करणे</a> – कृत्</b>',
            "तनादिः उभयपदी सकर्मकः अनिट् भिदादिः", "",
            "• क्त – कृत (कृतः, कृता, कृतम्)",          # include-list order;
            "• क्त्वा – कृत्वा",                       # 'नवीन' isn't included
            "• शतृ – कुर्वत् (कुर्वन्, कुर्वती, कुर्वत्/कुर्वद्)",
            "• अच् – कर (करः, करा, करम्)",
            "• ल्युट् – करण (करणम्)"])
        unused = next(w for w in self.warnings if "not found in the data" in w)
        self.assertIn("तव्य", unused)
        self.assertNotIn("क्त,", unused)
        self.assertIn("shuddha-krdanta: 1 baseindex(es) not in the dhatupatha, skipped: 99.9999",
                      self.warnings)

    def test_other_krt_labels(self):
        self.assertIn("- कृ-८-यङ्लुक्-कृत्;", self.parts["yangluk-krdanta"])
        self.assertTrue(self.parts["nic-krdanta"].startswith("HEADER:title=णिच्-कृत्\n"))


class TestLakaraPart(_Data):
    def test_list_entry(self):
        recs = self.records("shuddha-kartari")
        self.assertEqual(recs["- कृ-८-कर्तरि"][3:], [
            '• <a href="bword://kR-8-kartari-laT">कृ-८-कर्तरि-लट्</a>',
            '• <a href="bword://kR-8-kartari-loT">कृ-८-कर्तरि-लोट्</a>'])

    def test_ubhayapadi_entry(self):
        recs = self.records("shuddha-kartari")
        key = next(k for k in recs if k.startswith("- कृ-८-कर्तरि-लट्;"))
        self.assertIn(";करोति;", key)
        self.assertIn(";कुर्महे", key)
        self.assertEqual(recs[key][3:], [
            '<b><a href="bword://kR-8-kartari">डुकृञ् (कृ) करणे - कर्तरि</a></b>',
            "<b>लट् – परस्मैपदिरूपाणि</b>",
            "करोति कुरुतः कुर्वन्ति", "करोषि कुरुथः कुरुथ", "करोमि कुर्वः कुर्मः", "",
            "<b>लट् – आत्मनेपदिरूपाणि</b>",
            "कुरुते कुर्वाते कुर्वते", "कुरुषे कुर्वाथे कुरुध्वे", "कुर्वे कुर्वहे कुर्महे"])

    def test_alternatives(self):
        recs = self.records("shuddha-kartari")
        lot = next(v for k, v in recs.items() if k.startswith("- कृ-८-कर्तरि-लोट्;"))
        self.assertEqual(lot[5], "करोतु/कुरुतात् कुरुताम् कुर्वन्तु")   # some slots only
        lit = next(v for k, v in recs.items() if k.startswith("- एध्-कर्तरि-लिट्;"))
        self.assertEqual(lit[5:10], ["एधाञ्चक्रे1 / एधामास1", "एधाञ्चक्रे2 / एधामास2",
                                     "एधाञ्चक्रे3 / एधामास3", "&#45;-", "एधाञ्चक्रे4 / एधामास4"])

    def test_other_lakara_labels(self):
        self.assertIn("- कृ-८-णिच्-कर्मणि", self.parts["nic-karmani"])
        self.assertIn("- कृ-८-यङ्लुक्-कर्तरि-लट्;", self.parts["yangluk-kartari"])


class TestBuild(_Data):
    def test_all_links_resolve_after_build(self):
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
        self.assertIn("kR-8-kartari-loT", keys)
        self.assertEqual(links - keys, set())


class TestCli(_Data):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CONVERTER), *map(str, args)],
                              capture_output=True, text=True)

    def test_parts_limit_links(self):
        out = self.d / "out"
        res = self.run_cli("--data", self.data, "--output-dir", out,
                           "--parts", "dhatu,shuddha-kartari")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["dhatu.txt", "shuddha-kartari.txt"])
        text = (out / "dhatu.txt").read_text(encoding="utf-8")
        self.assertIn("bword://kR-8-kartari", text)
        self.assertNotIn("bword://kR-8-kRt", text)      # krt not written: not linked

    def test_errors(self):
        res = self.run_cli("--data", self.data, "--output-dir", self.d / "o", "--parts", "x")
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown part", res.stderr)
        write(self.data / "data.txt", json.dumps({"data": [dhatu("1", "", "", "1")]}))
        res = self.run_cli("--data", self.data, "--output-dir", self.d / "o")
        self.assertEqual(res.returncode, 2)
        self.assertIn("'dhatu' is empty", res.stderr)
        write(self.data / "data.txt", json.dumps({"data": []}))
        res = self.run_cli("--data", self.data, "--output-dir", self.d / "o")
        self.assertEqual(res.returncode, 2)
        self.assertIn("no entries", res.stderr)


if __name__ == "__main__":
    unittest.main()
