#!/usr/bin/env python3
"""Converts the Amarakosha master data (vagvibha/kosha, data/amarakosha)
into one `notes` dictionary file.

Inputs (CSV, first row = column headers; the header text for each field
comes from the config, so column order doesn't matter and other columns
are ignored). References are kanda.varga.shloka (`1.05.001`; `।` and
Devanagari digits also work):
  --shlokas      one row per verse: reference and verse text.
  --words        one row per word: headword, verse reference, position
                 within the verse, meaning, lingam, vachanam, and the ids
                 of its सुधा and क्षीरस्वामी commentary (a cell may list
                 several ids, comma-separated).
  --sudha        सुधा commentary: id and text.
  --kshirasvami  क्षीरस्वामी commentary: id and text.
  --vargas       varga reference (`1.05`) and name (`धीवर्गः`), shown on
                 word entries.

Output: a `notes` file with
  - one entry per verse, keyed by its id (e.g. AK-1-05-001), listing its
    words grouped by meaning, with Prev/Next links to neighbouring verses;
  - one entry per word, keyed by the word, with its details, links to all
    words of the same meaning (across the whole kosha) and to its verse.
Links use GoldenDict's bword:// scheme and always point at keys this file
defines; a dangling link is an error.

Usage:
  amarakosha_to_notes.py --data DIR --output amarakosha.txt [--config amarakosha.yaml]
      (DIR holds words.csv, shlokas.csv, sudha.csv, ks_words.csv, vargas.csv;
       --words/--shlokas/--sudha/--kshirasvami/--vargas override single files)

  --debug --varga 1.05   convert one varga only (for checking output);
                         links leaving that varga and missing commentary
                         ids become warnings.

Exit status 2 on a data problem, with a file:line message.
"""
import argparse
import csv
import html
import re
import sys
from collections import OrderedDict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import yaml  # noqa: E402

from errors import DictionaryBuildError  # noqa: E402
from transliteration import Translator  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "amarakosha.yaml"

DEV_TO_ASCII = str.maketrans("०१२३४५६७८९", "0123456789")
ASCII_TO_DEV = str.maketrans("0123456789", "०१२३४५६७८९")

TABLE_FIELDS = {
    "shlokas": {"ref", "text"},
    "words": {"word", "ref", "order", "meaning", "lingam", "vachanam", "sudha", "kshirasvami"},
    "sudha": {"id", "text"},
    "kshirasvami": {"id", "text"},
    "vargas": {"ref", "name"},
}
# --data DIR: default file name for each table.
DEFAULT_FILES = {"shlokas": "shlokas.csv", "words": "words.csv", "sudha": "sudha.csv",
                 "kshirasvami": "ks_words.csv", "vargas": "vargas.csv"}
REQUIRED_CONFIG = {"title", "id_format", "display_format", "columns"}


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except OSError as e:
        raise DictionaryBuildError(f"cannot read config: {e}", file=path)
    missing = REQUIRED_CONFIG - set(cfg)
    if missing:
        raise DictionaryBuildError(f"config is missing {sorted(missing)}", file=path)
    cols = cfg["columns"]
    for table, fields in TABLE_FIELDS.items():
        given = set((cols.get(table) or {}))
        if given != fields:
            raise DictionaryBuildError(
                f"columns.{table} must map exactly {sorted(fields)} "
                f"(missing {sorted(fields - given)}, unknown {sorted(given - fields)})", file=path)
    cfg.setdefault("placeholder_values", [])
    cfg.setdefault("kshirasvami_default", "")
    return cfg


def read_table(path: Path, columns: dict, placeholders) -> list:
    """Returns rows as {field: value, '_line': n}, columns found by header."""
    placeholders = {str(p).strip() for p in placeholders}
    try:
        f = open(path, "r", encoding="utf-8", newline="")
    except OSError as e:
        raise DictionaryBuildError(f"cannot read: {e}", file=path)
    with f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])]
        index = {}
        for field, name in columns.items():
            if name not in header:
                raise DictionaryBuildError(
                    f"no column '{name}' (for '{field}'); columns are {header}", file=path, line=1)
            index[field] = header.index(name)

        rows = []
        for line_no, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                continue
            rec = {"_line": line_no}
            for field, i in index.items():
                value = row[i].strip() if i < len(row) else ""
                rec[field] = "" if value in placeholders else value
            rows.append(rec)
    return rows


def parse_ref(text: str, parts: int = None):
    """'1.05.001' / '1।05।001' / '१।५।१' -> (1, 5, 1). None if not numeric."""
    pieces = [p.strip() for p in re.split(r"[.।]", text.translate(DEV_TO_ASCII))]
    if not pieces or not all(p.isdigit() for p in pieces):
        return None
    if parts is not None and len(pieces) != parts:
        return None
    return tuple(int(p) for p in pieces)


def split_ids(cell: str) -> list:
    """'1.04.15#2, 1.04.15#3' -> ['1.04.15#2', '1.04.15#3']."""
    return [i.strip() for i in re.split(r"[,;]", cell or "") if i.strip()]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text, quote=False)


def format_verse(text: str) -> list:
    """Breaks a verse into lines after each single danda and each double
    danda."""
    text = re.sub(r"।(?!।)", "।\n", text)
    text = re.sub(r"॥", "॥\n", text)
    return [esc(line.strip()) for line in text.split("\n") if line.strip()]


def link(target: str, label: str) -> str:
    return f'<a href="bword://{target}">{label}</a>'


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

class Converter:
    def __init__(self, cfg: dict, translator: Translator = None):
        self.cfg = cfg
        self.tr = translator or Translator()
        self.warnings = []

    def ref_id(self, ref) -> str:
        return self.cfg["id_format"].format(*ref)

    def ref_display(self, ref) -> str:
        return self.cfg["display_format"].format(*ref).translate(ASCII_TO_DEV)

    def word_key(self, word: str, where) -> str:
        try:
            return self.tr.translateWord(word)
        except DictionaryBuildError as e:
            raise e.with_location(*where)

    def word_link(self, w: dict) -> str:
        text = link(w["key"], esc(w["word"]))
        if w["lingam"]:
            text += f"({esc(w['lingam'])})"
        if w["vachanam"]:
            text += f"[{esc(w['vachanam'])}]"
        return text

    def problem(self, msg: str, strict: bool):
        if strict:
            raise DictionaryBuildError(msg)
        self.warnings.append(msg)

    def convert(self, tables: dict, files: dict, only_varga=None, lax=False) -> str:
        """tables/files: {table name: rows / file name for messages}.
        lax: report link/reference problems as warnings (debug runs)."""
        strict = not lax
        shloka_rows, word_rows = tables["shlokas"], tables["words"]
        shlokas_file, words_file = files["shlokas"], files["words"]

        # --- vargas and commentary ------------------------------------------
        vargas = {}
        for row in tables["vargas"]:
            where = (files["vargas"], row["_line"])
            ref = parse_ref(row["ref"], 2)
            if ref is None:
                raise DictionaryBuildError(
                    f"bad varga reference {row['ref']!r} (expected kanda.varga)", *where)
            if ref in vargas:
                raise DictionaryBuildError(f"duplicate varga {row['ref']!r}", *where)
            vargas[ref] = row["name"]

        commentary = {}
        for table in ("sudha", "kshirasvami"):
            texts = commentary[table] = {}
            for row in tables[table]:
                where = (files[table], row["_line"])
                if not row["id"]:
                    raise DictionaryBuildError("row without an id", *where)
                if row["id"] in texts:
                    raise DictionaryBuildError(f"duplicate id {row['id']!r}", *where)
                texts[row["id"]] = row["text"]

        # --- verses ---------------------------------------------------------
        verses = {}
        for row in shloka_rows:
            where = (shlokas_file, row["_line"])
            ref = parse_ref(row["ref"], 3)
            if ref is None:
                raise DictionaryBuildError(
                    f"bad verse reference {row['ref']!r} (expected kanda।varga।shloka)", *where)
            if ref in verses:
                raise DictionaryBuildError(
                    f"duplicate verse {row['ref']!r} (first at line {verses[ref]['_line']})", *where)
            if ref[:2] not in vargas:
                self.problem(f"{shlokas_file}:{row['_line']}: varga "
                             f"{'.'.join(map(str, ref[:2]))} is not in {files['vargas']}", strict)
            verses[ref] = {**row, "ref": ref, "id": self.ref_id(ref),
                           "varga_name": vargas.get(ref[:2], "")}
        if not verses:
            raise DictionaryBuildError("no verses", file=shlokas_file)
        order = sorted(verses)

        # --- words ----------------------------------------------------------
        words = []
        for row in word_rows:
            where = (words_file, row["_line"])
            if not row["word"]:
                self.warnings.append(f"{words_file}:{row['_line']}: no headword - skipped")
                continue
            ref = parse_ref(row["ref"], 3)
            if ref is None:
                raise DictionaryBuildError(f"bad verse reference {row['ref']!r}", *where)
            if ";" in row["word"] or row["word"].startswith("-"):
                raise DictionaryBuildError(
                    f"headword {row['word']!r} can't contain ';' or start with '-'", *where)
            if ref not in verses:
                self.problem(f"{words_file}:{row['_line']}: verse {row['ref']} of "
                             f"'{row['word']}' is not in {shlokas_file}", strict)
            texts = {}
            for table in ("sudha", "kshirasvami"):
                found = []
                for cid in split_ids(row[table]):
                    if cid in commentary[table]:
                        found.append(commentary[table][cid])
                    else:
                        self.problem(f"{words_file}:{row['_line']}: {table} id {cid!r} of "
                                     f"'{row['word']}' is not in {files[table]}", strict)
                texts[table] = [t for t in found if t]
            words.append({**row, "ref": ref, **texts,
                          "order": parse_ref(row["order"]) or (999,),
                          "key": self.word_key(row["word"], where)})
        words.sort(key=lambda w: (w["ref"], w["order"]))

        by_verse, by_meaning = {}, {}
        for w in words:
            by_verse.setdefault(w["ref"], []).append(w)
            if w["meaning"]:
                by_meaning.setdefault(w["meaning"], []).append(w)

        def selected(ref):
            return only_varga is None or ref[:2] == only_varga

        out_verses = [verses[r] for r in order if selected(r)]
        out_words = [w for w in words if selected(w["ref"])]
        if not out_verses:
            raise DictionaryBuildError(f"no verses in varga {only_varga}")

        # --- records --------------------------------------------------------
        records, links = [], []

        for v in out_verses:
            lines = [f"- e:{v['id']}", self.ref_display(v["ref"])]
            lines += format_verse(v["text"]) + [""]
            groups = OrderedDict()
            for w in by_verse.get(v["ref"], []):
                groups.setdefault(w["meaning"], []).append(w)
            for meaning, ws in groups.items():
                links += [w["key"] for w in ws]
                word_list = ", ".join(self.word_link(w) for w in ws)
                lines.append(f"• <b>अर्थः</b> – {esc(meaning)} ⇒ {word_list}" if meaning
                             else f"• {word_list}")
            i = order.index(v["ref"])
            nav = []
            if i > 0:
                prev = verses[order[i - 1]]
                nav.append(f"Prev:{link(prev['id'], self.ref_display(prev['ref']))}")
                links.append(prev["id"])
            if i < len(order) - 1:
                nxt = verses[order[i + 1]]
                nav.append(f"Next:{link(nxt['id'], self.ref_display(nxt['ref']))}")
                links.append(nxt["id"])
            if nav:
                lines += ["", ", ".join(nav)]
            records.append(lines)

        for w in out_words:
            lines = [f"- {w['word']}"]
            if w["meaning"]:
                lines.append(f"• <b>अर्थः</b> – {esc(w['meaning'])}")
            lingam = " ".join(filter(None, [esc(w["lingam"]),
                                            f"[{esc(w['vachanam'])}]" if w["vachanam"] else ""]))
            if lingam:
                lines.append(f"• <b>लिङ्गम्</b> – {lingam}")
            if w["sudha"]:
                lines.append("• <b>सुधा</b> – " + "<br>".join(esc(t) for t in w["sudha"]))
            kshira = [esc(t) for t in w["kshirasvami"]] or (
                [esc(self.cfg["kshirasvami_default"])] if self.cfg["kshirasvami_default"] else [])
            if kshira:
                lines.append("• <b>क्षीरस्वामी</b> – " + "<br>".join(kshira))

            synonyms, seen = [], {w["word"]}
            for s in by_meaning.get(w["meaning"], []) if w["meaning"] else []:
                if s["word"] not in seen:
                    seen.add(s["word"])
                    synonyms.append(s)
            if synonyms:
                links += [s["key"] for s in synonyms]
                lines += ["", "• <b>समानार्थकाः</b> – " + ", ".join(self.word_link(s) for s in synonyms)]

            v = verses.get(w["ref"])
            if v:
                links.append(v["id"])
                suffix = f" [{esc(v['varga_name'])}]" if v["varga_name"] else ""
                lines += ["", f"• {link(v['id'], self.ref_display(v['ref']))}{suffix}"]
                lines += format_verse(v["text"])
            records.append(lines)

        # --- checks ---------------------------------------------------------
        for lines in records:
            for line in lines[1:]:
                if line.startswith("-"):
                    raise DictionaryBuildError(
                        f"entry '{lines[0][2:]}' has a line starting with '-', which would "
                        f"start a new notes record: {line[:60]!r}")
        keys = {v["id"] for v in out_verses} | {w["key"] for w in out_words}
        dangling = sorted(set(links) - keys)
        if dangling:
            self.problem(f"{len(dangling)} link(s) to keys not in the output: "
                         f"{', '.join(dangling[:10])}{' ...' if len(dangling) > 10 else ''}",
                         strict)

        header = [f"HEADER:title={self.cfg['title']}", "HEADER:type=notes"]
        return "\n".join(header) + "\n\n" + "\n\n".join("\n".join(r) for r in records) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data", type=Path, help="directory with the five CSV files "
                   f"({', '.join(DEFAULT_FILES.values())})")
    for table in DEFAULT_FILES:
        p.add_argument(f"--{table}", type=Path, help=f"override {DEFAULT_FILES[table]}")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--debug", action="store_true",
                   help="allow --varga; data problems that would be errors become warnings")
    p.add_argument("--varga", help="debug only: convert just this varga, e.g. 1.05")
    args = p.parse_args(argv)

    if args.varga and not args.debug:
        p.error("--varga is only allowed with --debug (it can't validate links outside the varga)")
    files = {}
    for table, name in DEFAULT_FILES.items():
        given = getattr(args, table)
        if given is None and args.data is None:
            p.error(f"give --data DIR or --{table} FILE")
        files[table] = given if given is not None else args.data / name

    try:
        only = None
        if args.varga:
            only = parse_ref(args.varga, 2)
            if only is None:
                p.error(f"--varga must look like 1.05, got {args.varga!r}")
        cfg = load_config(args.config)
        conv = Converter(cfg)
        tables = {t: read_table(f, cfg["columns"][t], cfg["placeholder_values"])
                  for t, f in files.items()}
        text = conv.convert(tables, files, only_varga=only, lax=args.debug)
    except DictionaryBuildError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)

    for w in conv.warnings:
        print(f"⚠️  {w}", file=sys.stderr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"✅ {args.output}")


if __name__ == "__main__":
    main()
