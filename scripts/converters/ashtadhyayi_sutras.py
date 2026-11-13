#!/usr/bin/env python3
"""Converts the ashtadhyayi.com sutra data into `notes` dictionaries.

Input: --data DIR, the 'sutraani' folder of
https://github.com/ashtadhyayi-com/data (file names in the config):
  data.txt        the sutras (number, text, padaccheda, anuvritti, type, artha)
  sutrartha.txt   short ("sa") and detailed ("sd") explanation per sutra
  <commentary>    one JSON object {"<sutra index>": "<text>"} per commentary

Parts written to --output-dir (as <part>.txt):
  sutra           one entry per sutra: number, sutra, padaccheda,
                  anuvṛtti, artha (ss). Keys: number (१.१.०६३), the sutra,
                  its saṃjñā/paribhāṣā names and padaccheda words (config
                  padaccheda_keys: none / declined (default, no avyayas) / all)
  artha           one entry per sutra with a sutrārtha: bold short artha,
                  then the detailed one
  <commentary>    one entry per sutra that has a commentary
The artha and commentary parts are keyed by number and sutra, so a lookup
shows the sutra and everything about it together.

Sutra references in the text ([[७.२.१]], [[1.1.62]], <{SK294}>) become
bword:// links to the sutra number (keys are transliterated by the
dictionary builder, so १.१.०६२ is linked as 1.1.062). A reference that
doesn't parse or names no sutra is left as text and counted in a warning.
Links point at the 'sutra' part, so build it whenever you build others.

Usage:
  ashtadhyayi_sutras.py --data external/ac/sutraani --output-dir DIR
      [--config FILE] [--parts sutra,kashika]

Exit status 2 on a data problem.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ashtadhyayi_common import (  # noqa: E402
    CONFIG_DIR, DEV_TO_ASCII, DictionaryBuildError, KeyMaker, dev_digits, esc,
    link, load_config, load_json, notes_file, parse_parts, write_parts)

DEFAULT_CONFIG = CONFIG_DIR / "ashtadhyayi_sutras.yaml"
REQUIRED_CONFIG = {"base", "sutra_title", "artha", "commentaries", "key_types",
                   "avyaya_label", "padaccheda_keys", "tags"}
PADACCHEDA_KEY_MODES = ("none", "declined", "all")

SUTRA_NUM = r"[0-9०-९]+\s*[.।]\s*[0-9०-९]+\s*[.।]\s*[0-9०-९]+"

# Markup in sutrartha/commentary text, in priority order.
TOKEN_RE = re.compile(
    r"<<(?P<pq>[^<>]*?)>>\s*\[\[(?P<pr>[^\]]*)\]\]"       # <<sutra>> [[1.2.3]]
    r"|<<(?P<sq>[^<>]*?)>>\s*<\{SK(?P<sr>\d+)\}>"          # <<sutra>> <{SK12}>
    r"|\[\[(?P<ref>[^\]]*)\]\]"                            # [[1.2.3]]
    r"|<\{SK(?P<sk>\d+)\}>"                                # <{SK12}>
    r"|<\{(?P<curly>[^}]*)\}>"                             # <{उ5}> etc.
    r"|<<(?P<q>[^<>]*?)>>"                                 # <<quoted sutra>>
    r"|\{!\s*[0-9०-९]*\s*(?P<dhatu>[^!]*?)\s*!\}"          # {!1290 ओलजी!}
    r"|\{\$(?P<bold>.*?)\$\}"                              # {$ ... $}
    r"|(?P<stray>\{\$|\$\})"
    r"|<(?P<close>/?)(?P<tag>[A-Za-z][A-Za-z0-9]*)\b[^<>]*?/?>",
    re.S)
BREAK = "\x00"
QUOTE_WITH_NUM_RE = re.compile(rf"^(?P<text>.*?)\s+(?P<num>{SUTRA_NUM})$", re.S)


class Sutras:
    def __init__(self, cfg: dict, keymaker: KeyMaker = None):
        self.cfg = cfg
        self.key = keymaker or KeyMaker()
        self.rows = []          # sorted sutra rows
        self.by_index = {}      # "11063" -> row
        self.by_num = {}        # (1, 1, 63) -> row
        self.by_sk = {}         # Siddhanta-Kaumudi number -> row
        self.unresolved = {}    # part -> count of refs left as text

    # --- input ------------------------------------------------------------
    def load(self, data_dir: Path):
        path = data_dir / self.cfg["base"]
        data = load_json(path)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise DictionaryBuildError("expected {'data': [...]}", file=path)
        for r in rows:
            try:
                num = (int(r["a"]), int(r["p"]), int(r["n"]))
            except (KeyError, ValueError, TypeError):
                raise DictionaryBuildError(f"sutra {r.get('i')!r}: bad a/p/n", file=path)
            if r["i"] in self.by_index or num in self.by_num:
                raise DictionaryBuildError(f"duplicate sutra {r['i']}", file=path)
            r = dict(r, num=num)
            self.by_index[r["i"]] = r
            self.by_num[num] = r
            sk = str(r.get("skn") or "").strip()
            if sk and sk != "0":
                self.by_sk.setdefault(sk, r)
        self.rows = sorted(self.by_num.values(), key=lambda r: r["num"])

    # --- sutra numbers ------------------------------------------------------
    @staticmethod
    def num_text(num) -> str:
        """(1, 1, 63) -> '१.१.०६३' (the key; the builder indexes it as 1.1.063)."""
        return dev_digits(f"{num[0]}.{num[1]}.{num[2]:03d}")

    def num_target(self, num) -> str:
        return self.key(self.num_text(num))

    def parse_num(self, text: str):
        """'७.२.१' / '1.1.62' / '6।1।87' -> (7, 2, 1) if that sutra exists."""
        pieces = [p.strip() for p in re.split(r"[.।]", text.translate(DEV_TO_ASCII).strip())]
        if len(pieces) != 3 or not all(p.isdigit() for p in pieces):
            return None
        num = tuple(int(p) for p in pieces)
        return num if num in self.by_num else None

    def heading(self, r, suffix="") -> str:
        return f"<b>{self.num_text(r['num'])} {esc(r['s'].strip())} ।{suffix}</b>"

    # --- rich text ----------------------------------------------------------
    def render(self, text: str, part: str) -> list:
        """ashtadhyayi.com markup -> list of HTML lines."""
        html = self._render(text.replace("\r", ""), part)
        # BREAK marks a line break from a block tag: merge it with an
        # adjacent source newline rather than adding a blank line.
        html = re.sub(r"\n?(?:\x00)+\n?", "\n", html)
        lines = [ln.strip() for ln in html.replace("\t", "\n").split("\n")]
        out = []
        for ln in lines:
            if ln or (out and out[-1]):
                out.append(ln)
        while out and not out[-1]:
            out.pop()
        return out

    def _ref_link(self, num_text: str, label_html: str, part: str, show_num=True):
        num = self.parse_num(num_text)
        if num is None:
            self.unresolved[part] = self.unresolved.get(part, 0) + 1
            shown = f"[{esc(num_text.strip())}]" if show_num else ""
            return f"{label_html} {shown}".strip() if label_html else shown
        if label_html:
            return link(self.num_target(num), label_html) + (
                f" [{esc(num_text.strip())}]" if show_num else "")
        return link(self.num_target(num), f"[{esc(num_text.strip())}]")

    def _sk_link(self, sk: str, label_html: str, part: str):
        r = self.by_sk.get(sk)
        tag = f"[SK{esc(sk)}]"
        if r is None:
            self.unresolved[part] = self.unresolved.get(part, 0) + 1
            return (label_html + " " if label_html else "") + tag
        target = self.num_target(r["num"])
        return (link(target, label_html) + " " + tag) if label_html else link(target, tag)

    def _render(self, text: str, part: str) -> str:
        tags = self.cfg["tags"]
        out, pos = [], 0
        for m in TOKEN_RE.finditer(text):
            out.append(esc(text[pos:m.start()]))
            pos = m.end()
            g = m.groupdict()
            if g["pr"] is not None:
                out.append(self._ref_link(g["pr"], esc(g["pq"].strip()), part))
            elif g["sr"] is not None:
                out.append(self._sk_link(g["sr"], esc(g["sq"].strip()), part))
            elif g["ref"] is not None:
                out.append(self._ref_link(g["ref"], "", part))
            elif g["sk"] is not None:
                out.append(self._sk_link(g["sk"], "", part))
            elif g["curly"] is not None:
                out.append(f"[{esc(g['curly'].strip())}]")
            elif g["q"] is not None:
                q = g["q"].strip()
                mq = QUOTE_WITH_NUM_RE.match(q)
                if mq and self.parse_num(mq["num"]):
                    out.append(self._ref_link(mq["num"], esc(mq["text"]), part))
                else:
                    out.append(f"‘{esc(q)}’")
            elif g["dhatu"] is not None:
                out.append(esc(g["dhatu"]))      # dhatu links: a later round
            elif g["bold"] is not None:
                out.append(f"<b>{self._render(g['bold'], part).strip()}</b>")
            elif g["stray"] is not None:
                pass
            else:
                kind = tags.get(g["tag"].lower(), "strip")
                closing = bool(g["close"])
                if kind in ("b", "i", "u"):
                    out.append(f"</{kind}>" if closing else f"<{kind}>")
                elif kind == "bline":
                    out.append("</b>" + BREAK if closing else BREAK + "<b>")
                elif kind == "bullet":
                    out.append("" if closing else BREAK + "• ")
                elif kind == "line":
                    out.append(BREAK)
                elif kind == "br":
                    out.append("\n")
        out.append(esc(text[pos:]))
        return "".join(out)

    # --- sutra part ---------------------------------------------------------
    def padaccheda(self, pc: str) -> str:
        words = []
        for item in filter(None, pc.split("##")):
            f = item.split("$")
            word = esc(f[0].strip())
            if len(f) >= 4 and f[1] == "S" and f[2].strip() != "":
                v, c = f[2].strip(), f[3].strip()
                if v == "0":
                    word += f" ({self.cfg['avyaya_label']})"
                elif c:
                    word += f" ({dev_digits(v)}।{dev_digits(c)})"
            words.append(word)
        return " ".join(words)

    def padaccheda_keys(self, pc: str) -> list:
        mode = self.cfg["padaccheda_keys"]
        if mode == "none":
            return []
        keys = []
        for item in filter(None, pc.split("##")):
            f = item.split("$")
            if mode == "declined" and len(f) >= 3 and f[1] == "S" and f[2].strip() == "0":
                continue                          # avyaya
            keys.append(f[0])
        return keys

    def type_keys(self, typ: str) -> list:
        keys = []
        for item in filter(None, typ.split("##")):
            f = item.split("$")
            if len(f) >= 2 and f[0] in self.cfg["key_types"] and f[1].strip():
                keys.append(f[1])
        return keys

    def anuvritti(self, an: str) -> str:
        items = []
        for item in filter(None, an.split("##")):
            word, _, idx = item.partition("$")
            r = self.by_index.get(idx.strip())
            if r is None:
                self.unresolved["sutra"] = self.unresolved.get("sutra", 0) + 1
                items.append(esc(word.strip()))
            else:
                items.append(link(self.num_target(r["num"]), esc(word.strip())))
        return "अनुवृत्तिः – " + " ".join(items) if items else ""

    def keys_for(self, r) -> list:
        return [self.num_text(r["num"]), r["s"]]

    def sutra_part(self) -> str:
        records = []
        for r in self.rows:
            keys = self.keys_for(r) + self.type_keys(r.get("type", "")) + \
                self.padaccheda_keys(r.get("pc", ""))
            body = [self.heading(r)]
            for line in (self.padaccheda(r.get("pc", "")), self.anuvritti(r.get("an", "")),
                         esc((r.get("ss") or "").strip())):
                if line:
                    body.append(line)
            records.append((keys, body))
        return notes_file(self.cfg["sutra_title"], records, self.key)

    # --- artha and commentary parts -----------------------------------------
    def artha_part(self, sutrartha: dict) -> str:
        label = self.cfg["artha"]["label"]
        records = []
        for r in self.rows:
            sa = sutrartha.get(r["i"])
            if not isinstance(sa, dict):
                continue
            body = []
            if (sa.get("sa") or "").strip():
                body.append("<b>" + " ".join(self.render(sa["sa"], "artha")) + "</b>")
            if (sa.get("sd") or "").strip():
                body += self.render(sa["sd"], "artha")
            if body:
                records.append((self.keys_for(r), [self.heading(r, f" ({esc(label)})")] + body))
        return notes_file(label, records, self.key)

    def commentary_part(self, part: str, comm: dict) -> str:
        label = self.cfg["commentaries"][part]["label"]
        records = []
        for r in self.rows:
            text = comm.get(r["i"])
            if not isinstance(text, str) or not text.strip():
                continue
            body = [self.heading(r, f" ({esc(label)})")] + self.render(text, part)
            records.append((self.keys_for(r), body))
        return notes_file(label, records, self.key)


def part_names(cfg) -> list:
    return ["sutra", "artha", *cfg["commentaries"]]


def _load_mapping(path: Path) -> dict:
    data = load_json(path)
    if not isinstance(data, dict):
        raise DictionaryBuildError("expected {\"<index>\": ...}", file=path)
    return data


def convert(data_dir: Path, cfg: dict, wanted=None, keymaker=None):
    """Returns ({part: text}, warnings)."""
    if cfg["padaccheda_keys"] not in PADACCHEDA_KEY_MODES:
        raise DictionaryBuildError(f"config: padaccheda_keys must be one of "
                                   f"{', '.join(PADACCHEDA_KEY_MODES)}")
    s = Sutras(cfg, keymaker)
    s.load(data_dir)
    parts = {}
    if not wanted or "sutra" in wanted:
        parts["sutra"] = s.sutra_part()
    if not wanted or "artha" in wanted:
        parts["artha"] = s.artha_part(_load_mapping(data_dir / cfg["artha"]["file"]))
    for part, c in cfg["commentaries"].items():
        if wanted and part not in wanted:
            continue
        parts[part] = s.commentary_part(part, _load_mapping(data_dir / c["file"]))
    warnings = [f"{part}: {n} sutra reference(s) not resolved, left as text"
                for part, n in sorted(s.unresolved.items())] + s.key.warnings()
    return parts, warnings


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data", required=True, type=Path, help="the 'sutraani' folder")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--parts", help="comma-separated parts to write (default: all)")
    args = p.parse_args(argv)
    try:
        cfg = load_config(args.config, REQUIRED_CONFIG)
        wanted = parse_parts(args.parts, part_names(cfg))
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
