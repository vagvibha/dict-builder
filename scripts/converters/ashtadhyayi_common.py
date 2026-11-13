"""Shared helpers for the ashtadhyayi.com converters
(ashtadhyayi_sutras.py, ashtadhyayi_dhatus.py). Not a converter itself.

Both converters read JSON files from a checkout of
https://github.com/ashtadhyayi-com/data (usually fetched as a data-only,
sparse source into external/<name>/) and write one `notes` file per
"part" into --output-dir.
"""
import html
import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import yaml  # noqa: E402

from errors import DictionaryBuildError, UnmappedCharacterError  # noqa: E402
from transliteration import Translator  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parent / "config"

WS_RE = re.compile(r"[ \t]+")
DEV_TO_ASCII = str.maketrans("०१२३४५६७८९", "0123456789")
ASCII_TO_DEV = str.maketrans("0123456789", "०१२३४५६७८९")


def esc(text: str) -> str:
    """HTML-escapes text and neutralizes '*' (dict-builder reads `**` as
    bold markup)."""
    return html.escape(text, quote=False).replace("*", "&#42;")


def link(target: str, label: str) -> str:
    """A GoldenDict link. `target` is the transliterated key (what the
    dictionary builder turns a Devanagari key into); `label` is HTML."""
    return f'<a href="bword://{target}">{label}</a>'


def dev_digits(text) -> str:
    return str(text).translate(ASCII_TO_DEV)


def load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise DictionaryBuildError(f"cannot read: {e}", file=path)
    except json.JSONDecodeError as e:
        raise DictionaryBuildError(f"invalid JSON: {e.msg}", file=path, line=e.lineno)


def load_config(path: Path, required: set) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except OSError as e:
        raise DictionaryBuildError(f"cannot read: {e}", file=path)
    missing = required - set(cfg)
    if missing:
        raise DictionaryBuildError(f"config is missing {sorted(missing)}", file=path)
    return cfg


class KeyMaker:
    """Turns Devanagari keys into the transliterated form the dictionary
    builder will index them under, so bword:// links match."""
    def __init__(self, translator: Translator = None):
        self.tr = translator or Translator()
        self._cache = {}
        self.dropped = {}       # unmappable character -> count, see clean()

    def __call__(self, key: str) -> str:
        if key not in self._cache:
            self._cache[key] = self.tr.translateWord(key)
        return self._cache[key]

    def clean(self, key: str) -> str:
        """Drops characters the transliterator has no mapping for (e.g. the
        jihvamuliya sign in 'कुप्वोः ≍क≍पौ च'): a key must be indexable;
        the entry text keeps them. Counted in self.dropped."""
        while True:
            try:
                self.tr.translateWord(key)
                return key
            except UnmappedCharacterError as e:
                self.dropped[e.char] = self.dropped.get(e.char, 0) + key.count(e.char)
                key = WS_RE.sub(" ", key.replace(e.char, "")).strip()

    def warnings(self) -> list:
        return [f"dropped unmappable character {c!r} (U+{ord(c):04X}) from {n} key(s)"
                for c, n in sorted(self.dropped.items())]


def safe_body_line(line: str) -> str:
    """A body line starting with '-' would start a new notes record."""
    return "&#45;" + line[1:] if line.startswith("-") else line


def notes_file(title: str, records: list, keymaker: KeyMaker = None) -> str:
    """records: [(keys, body_lines)]. A key containing ';' (the notes key
    separator) becomes several keys; keys are deduped in order and empty
    ones dropped. Body lines are protected against starting a record."""
    out = [f"HEADER:title={title}", "HEADER:type=notes", ""]
    if not records:
        raise DictionaryBuildError(f"'{title}' would have no entries (wrong data folder?)")
    for keys, body in records:
        seen, uniq = set(), []
        for k in (piece.strip() for key in keys for piece in key.split(";")):
            if k and keymaker is not None:
                k = keymaker.clean(k)
            if k and k not in seen:
                seen.add(k)
                uniq.append(k)
        if not uniq:
            continue
        out.append("- " + ";".join(uniq))
        out.extend(safe_body_line(line) for line in body)
        out.append("")
    return "\n".join(out)


def write_parts(output_dir: Path, parts: dict, wanted=None) -> list:
    """parts: {part: text}. Writes <output_dir>/<part>.txt for each part
    (only those in `wanted`, if given). Returns the paths written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for part, text in parts.items():
        if wanted and part not in wanted:
            continue
        path = output_dir / f"{part}.txt"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def parse_parts(value, known) -> set:
    if not value:
        return None
    parts = {p.strip() for p in value.split(",") if p.strip()}
    unknown = parts - set(known)
    if unknown:
        raise DictionaryBuildError(f"unknown part(s) {sorted(unknown)}; known: {sorted(known)}")
    return parts


def split_alts(text: str, sep=",") -> list:
    return [t.strip() for t in text.split(sep) if t.strip()]
