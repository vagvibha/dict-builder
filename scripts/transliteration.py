#!/usr/bin/python3
"""Devanagari -> roman (itran-ish) transliteration.

The character mapping table itself lives in config/itrans.yaml, not in
this file, so it can be edited without touching code.
"""

from pathlib import Path

import yaml

from errors import UnmappedCharacterError

CONFIG_DIR = Path(__file__).resolve().parent / "config"
ITRANS_CONFIG_PATH = CONFIG_DIR / "itrans.yaml"


def load_itrans_mapping(path: Path = ITRANS_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Malformed itrans mapping file: {path}")
    return data


class Translator:
    def __init__(self, mapping: dict = None):
        self._mapping = mapping if mapping is not None else load_itrans_mapping()

    def _translate(self, word):
        xlateWord = ""

        for c in word:
            if (c >= u'\u093E') and (c <= u'\u094D'):
                # 'a' was automatically added for vya~njanam
                # so remove it if it is a maatraa or halant
                xlateWord = xlateWord[:-1]
            if c == u'\u094D':
                continue
            if c in self._mapping:
                xlateWord = xlateWord + self._mapping[c]
            elif ord(c) <= 0xFF:
                xlateWord = xlateWord + c
            else:
                raise UnmappedCharacterError(c, word)
            if (c >= u'\u0915') and (c <= u'\u0939'):
                # add 'a' automatically since the character mapping
                # for these is actually with 'a' - maatraa or halant follows
                xlateWord = xlateWord + "a"
        xlateWord = xlateWord.replace("kSh", "x")
        return xlateWord

    def translateWord(self, word, suffix=True):
        if word == "" or word.strip() == ",":  # avoid empty junk words '(eng)'
            return ""
        if word.isascii():
            if word.startswith("e:"):
                word = word[2:]
                suffix = False
            if suffix:
                xlateWord = word + "(eng)"
            else:
                xlateWord = word
        else:
            # non-ascii - translate
            xlateWord = self._translate(word)

        # Get rid of '|' - this is a separator in babylon format.
        if xlateWord and xlateWord[-1] == '|':
            xlateWord = xlateWord.replace('|', '')
        else:
            xlateWord = xlateWord.replace('|', '.')
        return xlateWord

    def translateWords(self, words, suffix=True):
        words = [self.translateWord(word, suffix=suffix) for word in words]
        return [word for word in words if word]
