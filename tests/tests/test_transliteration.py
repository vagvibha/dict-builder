import unittest

from tests import helpers  # noqa: F401  (sets sys.path)
from errors import UnmappedCharacterError
from transliteration import Translator


class TestTranslatorCustomMapping(unittest.TestCase):
    """Uses a tiny explicit mapping so the rules are tested in isolation."""

    def setUp(self):
        self.t = Translator(mapping={
            'अ': 'a', 'क': 'k', 'ष': 'Sh', 'र': 'r',
            '।': '|', '१': '1', '३': '3', '४': '4',
        })

    def test_ascii_gets_eng_suffix(self):
        self.assertEqual(self.t.translateWord("hello"), "hello(eng)")
        self.assertEqual(self.t.translateWord("hello", suffix=False), "hello")

    def test_e_prefix_strips_and_suppresses_suffix(self):
        self.assertEqual(self.t.translateWord("e:hello"), "hello")
        self.assertEqual(self.t.translateWords(["e:hello", "normal"]), ["hello", "normal(eng)"])

    def test_inherent_a_and_halant(self):
        self.assertEqual(self.t.translateWord("कर"), "kara")

    def test_ksh_becomes_x(self):
        self.assertEqual(self.t.translateWord("अक्षर"), "axara")

    def test_danda_trailing_removed_internal_becomes_dot(self):
        self.assertEqual(self.t.translateWord("अर।"), "ara")
        self.assertEqual(self.t.translateWord("१।३।४४", suffix=False), "1.3.44")

    def test_empty_and_comma_dropped(self):
        self.assertEqual(self.t.translateWord(""), "")
        self.assertEqual(self.t.translateWord(","), "")
        self.assertEqual(self.t.translateWords(["", "hello"]), ["hello(eng)"])

    def test_unmapped_character_raises(self):
        with self.assertRaises(UnmappedCharacterError) as ctx:
            self.t.translateWord("क一")
        self.assertIn("U+4E00", str(ctx.exception))


class TestTranslatorRealMapping(unittest.TestCase):
    """Sanity checks against config/itrans.yaml."""

    def setUp(self):
        self.t = Translator()

    def test_common_words(self):
        cases = {
            "कर्म": "karma",
            "सत्यं": "satyaM",
            "ज्ञान": "jNaana",
            "अक्षर": "axara",
            "राम।": "raama",
        }
        for src, expected in cases.items():
            with self.subTest(src=src):
                self.assertEqual(self.t.translateWord(src), expected)

    def test_devanagari_digits(self):
        self.assertEqual(self.t.translateWord("१।३।४४", suffix=False), "1.3.44")


if __name__ == "__main__":
    unittest.main()
