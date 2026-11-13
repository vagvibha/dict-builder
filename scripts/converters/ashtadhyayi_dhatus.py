#!/usr/bin/env python3
"""Converts the ashtadhyayi.com dhatu data into `notes` dictionaries.

Input: --data DIR, the 'dhatu' folder of https://github.com/ashtadhyayi-com/data:
  data.txt                the dhatupatha (one row per dhatu, by baseindex)
  dhatuforms_vidyut_*.txt krt / lakara forms keyed by baseindex (see config)

Parts written to --output-dir (as <part>.txt; names and files in the config):
  dhatu      one entry per dhatu, keys: dhatu, aupadeshika, artha and
             कृ-धातु; it links to the dhatu's entry in every other part.
             Plus one entry per dhatu + upasarga (प्र + इ -> प्रे), keyed by
             the combined form, with the Hindi meaning.
  krt parts  (shuddha-krdanta, nic-krdanta, san-krdanta, yang-krdanta,
             yangluk-krdanta) one entry per dhatu: कृ-कृत्, and every form
             as a key; only the pratyayas in the config's krt.include list
  lakara parts (shuddha-kartari, shuddha-karmani, nic-kartari ...
             yangluk-karmani): कृ-कर्तरि lists the lakaras, each a link to
             e.g. कृ-कर्तरि-लट्, whose entry has the 9 (or 18) forms, all of
             them keys.

Dhatus that occur more than once get a disambiguated name in the
part-specific keys (कृ-धातु stays on all of them): the gaṇa if that is
enough (भू-१-कृत्, भू-१० ...), otherwise gaṇa.number from the baseindex
(सिध्-१.४९-कृत्), which upstream keeps stable.

Rows with pada '-' are gaṇasūtras, not dhatus, and are skipped.

Usage:
  ashtadhyayi_dhatus.py --data external/ac/dhatu --output-dir DIR
      [--config FILE] [--parts dhatu,shuddha-krdanta,shuddha-kartari]

Links only point at parts being written, so with --parts the dhatu entry
links just to those. Every other part links back to the dhatu part, so
build it whenever you build others. Exit status 2 on a data problem.
"""
import argparse
import sys
from collections import Counter, OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ashtadhyayi_common import (  # noqa: E402
    CONFIG_DIR, DictionaryBuildError, KeyMaker, dev_digits, esc, link, load_config,
    load_json, notes_file, parse_parts, split_alts, write_parts)

DEFAULT_CONFIG = CONFIG_DIR / "ashtadhyayi_dhatus.yaml"
REQUIRED_CONFIG = {"base", "title", "dhatu_key", "gana_names", "pada_names", "karma_names",
                   "settva_names", "lakaras", "pada_headings", "krt", "parts"}


# ---------------------------------------------------------------------------
# Upasarga sandhi
# ---------------------------------------------------------------------------
# Words are handled as phoneme lists: consonants as bare letters ('क'),
# vowels as independent vowel letters ('अ', 'इ' ...), plus 'ं' and 'ः'.

VIRAMA = "्"
MATRA_TO_VOWEL = {"ा": "आ", "ि": "इ", "ी": "ई", "ु": "उ", "ू": "ऊ", "ृ": "ऋ", "ॄ": "ॠ",
                  "ॢ": "ऌ", "ॣ": "ॡ", "े": "ए", "ै": "ऐ", "ो": "ओ", "ौ": "औ"}
VOWEL_TO_MATRA = {v: m for m, v in MATRA_TO_VOWEL.items()}
VOWELS = set("अआइईउऊऋॠऌॡएऐओऔ")
MARKS = set("ंःँ")


def is_consonant(ch: str) -> bool:
    return "क" <= ch <= "ह" or ch in "क़ख़ग़ज़ड़ढ़फ़य़"


def to_phonemes(word: str) -> list:
    out = []
    for ch in word:
        if is_consonant(ch):
            out += [ch, "अ"]
        elif ch == VIRAMA:
            if out and out[-1] == "अ":
                out.pop()
        elif ch in MATRA_TO_VOWEL:
            if out and out[-1] == "अ":
                out[-1] = MATRA_TO_VOWEL[ch]
        else:
            out.append(ch)
    return out


def from_phonemes(ph: list) -> str:
    out = []
    for i, p in enumerate(ph):
        if p in VOWELS and i > 0 and is_consonant(ph[i - 1]):
            out.append(VOWEL_TO_MATRA.get(p, ""))
        else:
            out.append(p)
            if is_consonant(p) and (i + 1 == len(ph) or ph[i + 1] not in VOWELS):
                out.append(VIRAMA)
    return "".join(out)


VOICED = set("गघङजझञडढणदधनबभमयरलवह")
NASALS = set("ङञणनम")
LONG = {"इ": "ई", "उ": "ऊ", "ऋ": "ॠ", "अ": "आ"}


def _vowel_sandhi(a: str, b: str) -> list:
    """Final vowel of the upasarga + initial vowel of the dhatu."""
    if a in "अआ":
        if b in "अआ":
            return ["आ"]
        if b in "इई":
            return ["ए"]
        if b in "उऊ":
            return ["ओ"]
        if b in "ऋॠ":
            return ["आ", "र"]              # उपसर्गादृति धातौ: प्र + ऋच्छ् -> प्रार्च्छ्
        if b in "एओ":
            return [b]                     # एङि पररूपम्: प्र + एज् -> प्रेज्
        return ["औ" if b == "औ" else "ऐ"]  # वृद्धिरेचि
    if a in "इई":
        return ["ई"] if b in "इई" else ["य", b]
    if a in "उऊ":
        return ["ऊ"] if b in "उऊ" else ["व", b]
    return [a, b]


def _consonant_sandhi(up: list, d: list) -> list:
    """Upasarga ending in a consonant (सम्, उद्, निर्/दुर्, निस्/दुस्) + dhatu."""
    last, first = up[-1], d[0]
    body = up[:-1]
    if first in VOWELS:
        return body + (["र"] if last == "स" else [last]) + d
    if last == "म":
        return body + ["ं"] + d
    if last == "द":
        if first == "स" and len(d) > 1 and d[1] in "थत":
            d = d[1:]                      # उदः स्थास्तम्भोः: उद् + स्था -> उत्था
            first = d[0]
        if first == "ह":
            return body + ["द", "ध"] + d[1:]       # उद् + हृ -> उद्धृ
        if first == "श":
            return body + ["च", "छ"] + d[1:]       # उद् + श्वस् -> उच्छ्वस्
        if first in NASALS:
            return body + ["न"] + d
        if first == "ल":
            return body + ["ल"] + d
        if first in "चछ":
            return body + ["च"] + d
        if first in "जझ":
            return body + ["ज"] + d
        if first in "टठ":
            return body + ["ट"] + d
        if first in "डढ":
            return body + ["ड"] + d
        if first in VOICED:
            return body + ["द"] + d
        return body + ["त"] + d
    if last in "रस":                       # निर्/निस्, दुर्/दुस्
        if first == "र":                   # निर् + रस् -> नीरस्
            return body[:-1] + [LONG.get(body[-1], body[-1])] + d
        if first in VOICED:
            return body + ["र"] + d
        if first in "कखपफ":                # इदुदुपधस्य चाप्रत्ययस्य: निष्कृ
            return body + ["ष"] + d
        if first in "चछ":
            return body + ["श"] + d
        if first in "टठ":
            return body + ["ष"] + d
        if first in "तथ":
            return body + ["स"] + d
        return body + ["ः"] + d
    return up + d


def _natva_satva(up: list, d: list, aupadeshik: str) -> list:
    """णोपदेश dhatus take ण after an upasarga with र (प्र + णम् -> प्रणम्);
    षोपदेश dhatus take ष after one ending in इ/उ (नि + षिध् -> निषिध्,
    अधि + ष्ठा -> अधिष्ठा)."""
    d = list(d)
    if aupadeshik.startswith("ण") and d[0] == "न" and "र" in up:
        d[0] = "ण"
    if aupadeshik.startswith("ष") and d[0] == "स" and up[-1] in "इईउऊ":
        d[0] = "ष"
        if len(d) > 1 and d[1] in "तथ":
            d[1] = {"त": "ट", "थ": "ठ"}[d[1]]
    return d


def upasarga_sandhi(upasargas: list, dhatu: str, aupadeshik: str = "") -> str:
    """['सम्', 'आ'] + 'कृ' -> 'समाकृ'. The upasarga nearest the dhatu is
    joined first. Covers the regular cases (vowel sandhi, final म्/द्/र्/स्,
    णत्व and षत्व by the aupadeshika); not irregulars like सम् + कृ -> संस्कृ."""
    d = to_phonemes(dhatu)
    for i, up in enumerate(reversed(upasargas)):
        u = to_phonemes(up)
        if not u or not d:
            continue
        if i == 0:
            d = _natva_satva(u, d, aupadeshik)
        if u[-1] in VOWELS and d[0] in VOWELS:
            d = u[:-1] + _vowel_sandhi(u[-1], d[0]) + d[1:]
        elif u[-1] in VOWELS or u[-1] in MARKS:
            d = u + d
        else:
            d = _consonant_sandhi(u, d)
    return from_phonemes(d)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

class Dhatus:
    def __init__(self, cfg: dict, keymaker: KeyMaker = None):
        self.cfg = cfg
        self.key = keymaker or KeyMaker()
        self.rows = []        # dhatus in baseindex order
        self.names = {}       # baseindex -> disambiguated name (कृ / भू-१ / सिध्-१.४९)
        self.skipped = 0
        self.krt_seen = set()  # included pratyayas found in some krt file

    def load(self, data_dir: Path):
        path = data_dir / self.cfg["base"]
        data = load_json(path)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise DictionaryBuildError("expected {'data': [...]}", file=path)
        seen = set()
        for r in rows:
            bi = str(r.get("baseindex", "")).strip()
            if not bi or bi in seen:
                raise DictionaryBuildError(f"missing or duplicate baseindex {bi!r}", file=path)
            seen.add(bi)
            if r.get("pada") == "-":
                self.skipped += 1          # a gaṇasūtra, not a dhatu
                continue
            for field in ("dhatu", "gana", "pada"):
                if not str(r.get(field, "")).strip():
                    raise DictionaryBuildError(f"dhatu {bi}: '{field}' is empty", file=path)
            self.rows.append(r)
        self.rows.sort(key=lambda r: r["baseindex"])
        self._disambiguate()

    def _disambiguate(self):
        by_dhatu = Counter(r["dhatu"] for r in self.rows)
        by_gana = Counter((r["dhatu"], r["gana"]) for r in self.rows)
        for r in self.rows:
            d, g = r["dhatu"], str(int(r["gana"]))
            if by_dhatu[d] == 1:
                name = d
            elif by_gana[(r["dhatu"], r["gana"])] == 1:
                name = f"{d}-{dev_digits(g)}"
            else:
                num = int(r["baseindex"].split(".")[-1])
                name = f"{d}-{dev_digits(g)}.{dev_digits(num)}"
            self.names[r["baseindex"]] = name

    # --- shared pieces ----------------------------------------------------
    def title(self, r) -> str:
        """डुकृञ् (कृ) करणे"""
        aup, d = (r.get("aupadeshik") or "").strip(), r["dhatu"].strip()
        text = f"{aup} ({d})" if aup and aup != d else d
        artha = (r.get("artha") or "").strip()
        return esc(f"{text} {artha}" if artha else text)

    def info(self, r) -> str:
        """तनादिः उभयपदी सकर्मकः अनिट् भिदादिः"""
        c = self.cfg
        words = [c["gana_names"].get(int(r["gana"])), c["pada_names"].get(r.get("pada")),
                 c["karma_names"].get(r.get("karma")), c["settva_names"].get(r.get("settva"))]
        words += split_alts(r.get("antarganas") or "")
        return esc(" ".join(w for w in words if w))

    def dhatu_key(self, r) -> str:
        """The unique key of the dhatu entry (कृ-धातु / भू-१-धातु)."""
        return f"{self.names[r['baseindex']]}-{self.cfg['dhatu_key']}"

    def part_key(self, r, label: str, *more) -> str:
        return "-".join([self.names[r["baseindex"]], label, *more])

    def header(self, r, linked=True) -> list:
        title = link(self.key(self.dhatu_key(r)), self.title(r)) if linked else self.title(r)
        return [f"<b>{title}</b>", self.info(r), ""]

    # --- dhatu part ---------------------------------------------------------
    def dhatu_part(self, forms: dict) -> str:
        """forms: {part: {baseindex: ...}} for the parts being written."""
        records = []
        for r in self.rows:
            bi = r["baseindex"]
            keys = [r["dhatu"], r.get("aupadeshik", ""), r.get("artha", ""),
                    f"{r['dhatu']}-{self.cfg['dhatu_key']}", self.dhatu_key(r)]
            body = self.header(r, linked=False)
            hindi = (r.get("artha_hindi") or "").strip()
            if hindi:
                body.insert(2, esc(hindi))
            for kind in ("krt", "lakara"):
                links = [link(self.key(self.part_key(r, p["label"])), esc(p["label"]))
                         for name, p in self.cfg["parts"].items()
                         if p["kind"] == kind and bi in forms.get(name, {})]
                if links:
                    body.append("• " + ", ".join(links))
            while body and not body[-1]:
                body.pop()
            records.append((keys, body))

            # Upasarga entries: one per combined form (meanings merged).
            combined = OrderedDict()
            for u in r.get("upasargas") or []:
                chain = [p.strip() for p in str(u.get("name", "")).split("+") if p.strip()]
                if not chain:
                    continue
                form = upasarga_sandhi(chain, r["dhatu"], r.get("aupadeshik", ""))
                meaning = (u.get("artha_hindi") or "").strip()
                combined.setdefault(form, [])
                if meaning and meaning not in combined[form]:
                    combined[form].append(meaning)
            for form, meanings in combined.items():
                ubody = [esc(m) for m in meanings] + [""]
                ubody += [link(self.key(self.dhatu_key(r)), self.title(r)), self.info(r)]
                records.append(([form], ubody))
        return notes_file(self.cfg["title"], records, self.key)

    # --- krt parts ----------------------------------------------------------
    def krt_order(self, row_forms: dict) -> list:
        """The configured pratyayas this dhatu has, in config order."""
        found = [k for k in self.cfg["krt"]["include"] if k in row_forms]
        self.krt_seen.update(found)
        return found

    @staticmethod
    def krt_display(value: str):
        """'भूत,भूतः,भूता,भूतम्' -> ('भूत (भूतः, भूता, भूतम्)', keys).
        ';' separates alternative sets, '/' alternative forms."""
        shown, keys = [], []
        for alt in filter(None, (a.strip() for a in value.split(";"))):
            fields = [f.strip() for f in alt.split(",")]
            stem, rest = fields[0], [f for f in fields[1:] if f]
            if not stem and not rest:
                continue
            keys += [w for f in [stem, *rest] for w in split_alts(f, "/")]
            shown.append(esc(stem) + (f" ({esc(', '.join(rest))})" if rest else ""))
        return " / ".join(shown), keys

    def krt_part(self, part: str, data: dict) -> str:
        label = self.cfg["parts"][part]["label"]
        records = []
        for r in self.rows:
            row = data.get(r["baseindex"])
            if not isinstance(row, dict):
                continue
            keys, lines = [self.part_key(r, label)], []
            for pratyaya in self.krt_order(row):
                shown, fkeys = self.krt_display(str(row[pratyaya]))
                if shown:
                    lines.append(f"• {esc(pratyaya)} – {shown}")
                    keys += fkeys
            if not lines:
                continue
            body = self.header(r)
            body[0] = body[0][:-4] + f" – {esc(label)}</b>"
            records.append((keys, body + lines))
        return notes_file(label, records, self.key)

    # --- lakara parts -------------------------------------------------------
    def lakara_rows(self, row: dict):
        """Yields (lakara code, name, {pada: [[alternatives] x 9]}) in config order."""
        for code, name in self.cfg["lakaras"].items():
            padas = OrderedDict()
            for pada in ("p", "a"):
                value = row.get(pada + code)
                if value:
                    padas[pada] = [split_alts(f) for f in value.split(";")]
            if padas:
                yield code, name, padas

    @staticmethod
    def forms_lines(forms: list) -> list:
        """9 slots -> 3 lines of 3; if every slot has alternatives, one slot
        per line ('a / b') with '--' between the purushas."""
        if all(len(f) > 1 for f in forms):
            lines = []
            for i, f in enumerate(forms):
                if i and i % 3 == 0:
                    lines.append("--")
                lines.append(esc(" / ".join(f)))
            return lines
        return [" ".join(esc("/".join(f)) for f in forms[i:i + 3])
                for i in range(0, len(forms), 3)]

    def lakara_part(self, part: str, data: dict) -> str:
        label = self.cfg["parts"][part]["label"]
        headings = self.cfg["pada_headings"]
        records = []
        for r in self.rows:
            row = data.get(r["baseindex"])
            if not isinstance(row, dict):
                continue
            lakaras = list(self.lakara_rows(row))
            if not lakaras:
                continue
            list_key = self.part_key(r, label)
            items = [f"• {link(self.key(self.part_key(r, label, name)), esc(self.part_key(r, label, name)))}"
                     for _, name, _ in lakaras]
            records.append(([list_key], self.header(r) + items))
            back = f"<b>{link(self.key(list_key), self.title(r) + ' - ' + esc(label))}</b>"
            for _, name, padas in lakaras:
                keys = [self.part_key(r, label, name)]
                body = self.header(r) + [back]
                for i, (pada, forms) in enumerate(padas.items()):
                    if i:
                        body.append("")
                    body.append(f"<b>{esc(name)} – {esc(headings[pada])}</b>")
                    body += self.forms_lines(forms)
                    keys += [w for f in forms for w in f]
                records.append((keys, body))
        return notes_file(label, records, self.key)


def convert(data_dir: Path, cfg: dict, wanted=None, keymaker=None):
    """Returns ({part: text}, warnings)."""
    dh = Dhatus(cfg, keymaker)
    dh.load(data_dir)
    forms, parts = {}, {}
    for part, p in cfg["parts"].items():
        if wanted and part not in wanted:
            continue
        if p.get("kind") not in ("krt", "lakara"):
            raise DictionaryBuildError(f"part '{part}': kind must be krt or lakara")
        data = load_json(data_dir / p["file"])
        if not isinstance(data, dict):
            raise DictionaryBuildError("expected {\"<baseindex>\": {...}}", file=data_dir / p["file"])
        forms[part] = data
        parts[part] = (dh.krt_part if p["kind"] == "krt" else dh.lakara_part)(part, data)
    if not wanted or "dhatu" in wanted:
        parts = {"dhatu": dh.dhatu_part(forms), **parts}
    warnings = []
    if any(cfg["parts"][p]["kind"] == "krt" for p in forms):
        unused = [k for k in cfg["krt"]["include"] if k not in dh.krt_seen]
        if unused:
            warnings.append(f"krt: included pratyaya(s) not found in the data: {', '.join(unused)}")
    known = {r["baseindex"] for r in dh.rows}
    for part, data in forms.items():
        extra = sorted(set(data) - known)
        if extra:
            warnings.append(f"{part}: {len(extra)} baseindex(es) not in the dhatupatha, skipped: "
                            f"{', '.join(extra[:5])}")
    return parts, warnings + dh.key.warnings()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data", required=True, type=Path, help="the 'dhatu' folder")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--parts", help="comma-separated parts to write (default: all)")
    args = p.parse_args(argv)
    try:
        cfg = load_config(args.config, REQUIRED_CONFIG)
        wanted = parse_parts(args.parts, ["dhatu", *cfg["parts"]])
        parts, warnings = convert(args.data, cfg, wanted)
    except DictionaryBuildError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    for w in warnings:
        print(f"⚠️  {w}", file=sys.stderr)
    for path in write_parts(args.output_dir, parts):
        print(f"✅ {path}")


if __name__ == "__main__":
    main()
