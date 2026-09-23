import unittest

from tests.helpers import PassthroughTranslator
from errors import DictionaryBuildError
from input_handlers import (DictionaryInputHandler, HandlerFactory,
                            NotesInputHandler, ShlokaInputHandler)
from transliteration import Translator


class TestHandlerFactory(unittest.TestCase):
    def test_known_types(self):
        for name, cls in (("one-liner", DictionaryInputHandler),
                          ("notes", NotesInputHandler),
                          ("shloka", ShlokaInputHandler)):
            with self.subTest(name=name):
                self.assertIsInstance(HandlerFactory.getInputHandler(name, exclusion_list=[]), cls)

    def test_unknown_type(self):
        with self.assertRaises(DictionaryBuildError):
            HandlerFactory.getInputHandler("bogus", exclusion_list=[])


# =====================================================================
# one-liner
# =====================================================================
class TestOneLiner(unittest.TestCase):
    def setUp(self):
        self.h = DictionaryInputHandler(PassthroughTranslator())

    def run_(self, text, headers=None):
        return self.h.process_stream(text, headers or {})

    def test_basic(self):
        self.assertEqual(self.run_("- hello entry ((this;that))"),
                         [{'words': ['that', 'this'],
                           'entry': 'hello entry<br>this; that<br>[unknown]'}])

    def test_title_header_is_source(self):
        res = self.run_("- x ((w))", {'title': 'RigVeda'})
        self.assertTrue(res[0]['entry'].endswith('<br>[RigVeda]'))

    def test_inline_source_is_sticky(self):
        res = self.run_("- a ((w1))\n[Gita][Bhashya]\n- b ((w2))\n- c ((w3))\n[VS]\n- d ((w4))")
        self.assertEqual([r['entry'].rsplit('<br>', 1)[1] for r in res],
                         ['[unknown]', '[Gita; Bhashya]', '[Gita; Bhashya]', '[VS]'])

    def test_cutoff_at_first_marker(self):
        res = self.run_("- text {{hidden}} more ((w))\n- other ((w2)) {{x}}")
        self.assertEqual(res[0]['entry'].split('<br>')[0], 'text')
        self.assertEqual(res[1]['entry'].split('<br>')[0], 'other')

    def test_empty_tokens_dropped(self):
        res = self.run_("- t ((a;;b; ;))")
        self.assertEqual(res[0]['entry'], 't<br>a; b<br>[unknown]')

    def test_line_without_keys_is_skipped(self):
        self.assertEqual(self.run_("- flashcard only line"), [])

    def test_comment_skipped(self):
        self.assertEqual(self.run_("# a comment\n- x ((w))")[0]['words'], ['w'])

    def test_bad_record_reports_line(self):
        self.h.filename = "f.txt"
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.h.process_stream("- ok ((w))\n\nbad line", {'title': 't'}, line_offset=2)
        self.assertEqual((ctx.exception.file, ctx.exception.line), ("f.txt", 5))

    def test_numeric_keys_dropped(self):
        self.assertEqual(self.run_("- t ((12;w;१२))")[0]['words'], ['w'])

    def test_one_liner_ignores_exclusions(self):
        h = DictionaryInputHandler(PassthroughTranslator(), exclusion_list=['w'])
        self.assertEqual(h.process_stream("- t ((w))", {})[0]['words'], ['w'])


# =====================================================================
# notes
# =====================================================================
class TestNotes(unittest.TestCase):
    def setUp(self):
        self.h = NotesInputHandler(PassthroughTranslator())

    def test_multiline_records(self):
        res = self.h.process_stream("- a;b\nline1\n\nline2\n- c\nz", {'title': 'N'})
        self.assertEqual(res, [
            {'words': ['a', 'b'], 'entry': '<br>line1<br><br>line2<br>a; b<br>[N]'},
            {'words': ['c'], 'entry': '<br>z<br>c<br>[N]'},
        ])

    def test_key_whitespace_and_trailing_semicolon(self):
        res = self.h.process_stream("-  p ;  s  ; m ; \nbody", {'title': 'T'})
        self.assertEqual(res[0]['words'], ['m', 'p', 's'])
        self.assertEqual(res[0]['entry'], '<br>body<br>p; s; m<br>[T]')

    def test_key_only_record(self):
        self.assertEqual(self.h.process_stream("- k", {})[0]['entry'], '<br><br>k<br>[unknown]')

    def test_empty(self):
        self.assertEqual(self.h.process_stream("   ", {}), [])
        self.assertEqual(self.h.process_stream("\n\n", {}), [])


# =====================================================================
# shloka
# =====================================================================
class TestShloka(unittest.TestCase):
    def setUp(self):
        self.h = ShlokaInputHandler(PassthroughTranslator(), exclusion_list=[])

    def words(self, text, headers=None):
        res = self.h.process_stream(text, headers or {})
        self.assertEqual(len(res), 1, res)
        return res[0]['words']

    def entry(self, text, headers=None):
        return self.h.process_stream(text, headers or {})[0]['entry']

    # --- auto-derived keys ---------------------------------------------
    def test_auto_derived_words(self):
        text = "अहो बत महत्पापं ।\nलोभेन हन्तुं ॥१-४५॥"
        self.assertEqual(self.words(text), sorted(['अहो', 'बत', 'महत्पापं', 'लोभेन', 'हन्तुं']))
        self.assertEqual(self.entry(text, {'title': 'T'}),
                         'अहो बत महत्पापं ।<br>लोभेन हन्तुं ॥१-४५॥<br>[T]')

    def test_records_split_on_blank_line(self):
        res = self.h.process_stream("a b ॥१॥\n\nc d ॥२॥", {})
        self.assertEqual([r['words'] for r in res], [['a', 'b'], ['c', 'd']])

    def test_punctuation_is_a_separator(self):
        text = 'निनिन्द रूपं, हृदयेन।पार्वती ?चारुता "उक्तम्" [अ] {ब} x;y z:w q!r s|t ‘म’ “न” ॥१॥'
        self.assertEqual(self.words(text), sorted(
            ['निनिन्द', 'रूपं', 'हृदयेन', 'पार्वती', 'चारुता', 'उक्तम्', 'अ', 'ब',
             'x', 'y', 'z', 'w', 'q', 'r', 's', 't', 'म', 'न']))

    def test_verse_numbers_dropped(self):
        self.assertEqual(self.words("a ॥ १-२ ॥ b ॥1.45॥ ॥३॥ 2345"), ['a', 'b'])

    def test_bold_tags_not_glued(self):
        self.assertEqual(self.words("<b>राम</b> गच्छति"), ['गच्छति', 'राम'])

    def test_exclusions(self):
        h = ShlokaInputHandler(PassthroughTranslator(), exclusion_list=['च'])
        res = h.process_stream("राम च सीता च", {'skip': ['सीता']})
        self.assertEqual(res[0]['words'], ['राम'])

    def test_duplicates_removed(self):
        self.assertEqual(self.words("a b a B"), ['a', 'b'])

    # --- notes / meta lines -------------------------------------------
    def test_notes_section(self):
        # A whitespace-only line is kept as an empty note line; a truly
        # blank line would end the record.
        text = "a b ॥१॥\n====\nHello\n \nWorld\n"
        self.assertEqual(self.entry(text), 'a b ॥१॥<br>====<br>Hello<br><br>World<br>[unknown]')

    def test_blank_line_ends_record(self):
        res = self.h.process_stream("a ॥१॥\n====\nnote\n\nb ॥२॥", {})
        self.assertEqual([r['words'] for r in res], [['a'], ['b']])

    def test_trailing_empty_divider_removed(self):
        self.assertNotIn("====", self.entry("a b c\n====\n   "))

    def test_plus_adds_verbatim(self):
        words = self.words("a ॥१॥\n====\n+ e:KS5-01;x.y;z")
        self.assertEqual(words, sorted(['a', 'e:KS5-01', 'x.y', 'z']))

    def test_plus_line_hidden_from_entry(self):
        self.assertNotIn("+ x", self.entry("a\n====\n+ x\nnote"))

    def test_minus_excludes(self):
        self.assertEqual(self.words("a b c\n====\n- b; c"), ['a'])

    def test_minus_all_drops_derived(self):
        self.assertEqual(self.words("a b\n====\n- all\n+ x"), ['x'])

    def test_double_plus_replaces_derived(self):
        text = "a b\n====\n++ नमः\nnote"
        self.assertEqual(self.words(text), ['नमः'])
        self.assertIn("++ नमः", self.entry(text))

    def test_double_plus_strips_punctuation_and_parens(self):
        self.assertEqual(self.words("a b\n====\n++ नमस्ते । कथं ? (अपि)"), sorted(['नमस्ते', 'कथं']))

    def test_double_plus_nested_and_unbalanced_parens(self):
        self.assertEqual(self.words("a\n====\n++ x (y (z) w) v (u"), ['u', 'v', 'x'])

    def test_double_plus_bold(self):
        self.assertEqual(self.words("a\n====\n++ <b>x</b>y z"), ['xy', 'z'])

    # --- auto_shloka header -------------------------------------------
    def test_auto_shloka_false(self):
        text = "a b ॥१॥\n====\n+ k1;k2"
        self.assertEqual(self.words(text, {'auto_shloka': False}), ['k1', 'k2'])
        self.assertEqual(self.words(text, {'auto_shloka': True}), ['a', 'b', 'k1', 'k2'])

    def test_auto_shloka_false_with_double_plus(self):
        self.assertEqual(self.words("a b\n====\n++ c d\n+ e", {'auto_shloka': False}),
                         ['c', 'd', 'e'])

    def test_auto_shloka_false_no_keys_skips_record(self):
        self.assertEqual(self.h.process_stream("a b ॥१॥", {'auto_shloka': False}), [])


class TestShlokaKey(unittest.TestCase):
    """shlokakey needs the real translator (it converts Devanagari digits)."""

    def setUp(self):
        self.h = ShlokaInputHandler(Translator(), exclusion_list=[])

    def words(self, text, headers):
        return self.h.process_stream(text, headers)[0]['words']

    def test_formats(self):
        cases = [
            ("a b ॥232॥", 'VC,1', 'VC-232'),
            ("a b ॥1.45॥", 'BG,2,2', 'BG-01-45'),
            ("a b ॥१-४५॥", 'BG,2,2', 'BG-01-45'),
            ("a b ॥१।१॥", 'KA,2,2', 'KA-01-01'),
            ("a b ॥1.1.5॥", 'BR,1,1,3', 'BR-1-1-005'),
        ]
        for text, key, expected in cases:
            with self.subTest(key=key, text=text):
                self.assertIn(expected, self.words(text, {'shlokakey': key}))

    def test_no_verse_marker_no_key(self):
        self.assertEqual(self.words("a b", {'shlokakey': 'VC,1'}), ['a(eng)', 'b(eng)'])

    def test_depth_mismatch_raises(self):
        with self.assertRaises(DictionaryBuildError) as ctx:
            self.h.process_stream("a ॥४॥", {'shlokakey': 'XX,1,1,3'})
        self.assertIn("expects 3 tiers, but found 1", str(ctx.exception))

    def test_nokey(self):
        self.assertEqual(self.words("wordA wordB ॥10॥\n====\n- wordB; nokey", {'shlokakey': 'XX,1'}),
                         ['wordA(eng)'])

    def test_all_and_nokey(self):
        self.assertEqual(self.words("a b ॥10॥\n====\n- all; nokey\n+ x", {'shlokakey': 'BG,1'}),
                         ['x(eng)'])

    def test_all_keeps_key(self):
        self.assertEqual(self.words("a b ॥10॥\n====\n- all\n+ x", {'shlokakey': 'BG,1'}),
                         ['BG-10', 'x(eng)'])


if __name__ == "__main__":
    unittest.main()
