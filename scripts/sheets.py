"""Downloads Google Sheets tabs into the content directory as record
files ('sheets:' in <content-dir>/meta.yaml; format in record_input.py):

    sheets:
      - path: contents/misc/words.txt     # relative to the workspace; a .txt in the content dir
        url: https://docs.google.com/spreadsheets/d/<id>/edit?gid=123#gid=123
        tab: Words                        # the tab's name in the sheet
      - path: contents/misc/other.txt
        url: https://docs.google.com/spreadsheets/d/<id>/edit
        tab: Other                        # no gid in the url: found by name
        fetch: false                      # keep the committed file as it is

The spreadsheets stay private: each one is shared (Viewer) with a Google
service account, and tabs are read through the Sheets API as that account.
Which tab: the url's #gid=, the 'tab' name, or both. With both, they
must agree (the tab is checked to still have that name), so renaming a
tab in the sheet fails the sync until the config is updated. Credentials:
  GOOGLE_SERVICE_ACCOUNT_JSON     the key file's contents (GitHub Actions secret)
  GOOGLE_APPLICATION_CREDENTIALS  a path to the key file (handy locally)
Values are read as formatted, i.e. as shown in the sheet.

Every cell is tidied the same way, so git only shows real changes:
Unicode NFC, no-break spaces -> spaces, LF line breaks, trimmed; empty
trailing rows/columns dropped.

All or nothing: every file must also parse as a record dictionary file
exactly as the build reads it; if any download or check fails, nothing
is written. The sync is one way: each run overwrites the files.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

from errors import DictionaryBuildError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
API = "https://sheets.googleapis.com/v4/spreadsheets"
SHEET_KEYS = {"path", "url", "tab", "fetch"}


def parse_url(url: str):
    """-> (spreadsheet id, gid or None), or None if there's no spreadsheet id."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        return None
    g = re.search(r"[#&?]gid=(\d+)", url)
    return m.group(1), int(g.group(1)) if g else None


def load_sheets_config(raw: list, workspace: Path, meta_path: Path, content_dir: Path) -> list:
    """Validates the 'sheets:' list. Returns [{path (Path), rel, url, tab, fetch}]."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DictionaryBuildError("'sheets' must be a list", file=meta_path)
    out, seen = [], set()
    ws = workspace.resolve()
    content = content_dir.resolve()
    for i, item in enumerate(raw):
        where = f"sheets[{i}]"
        if not isinstance(item, dict):
            raise DictionaryBuildError(f"{where} must be a mapping", file=meta_path)
        unknown = set(item) - SHEET_KEYS
        if unknown:
            raise DictionaryBuildError(f"{where}: unknown keys {sorted(unknown)}", file=meta_path)
        rel = str(item.get("path") or "").strip()
        if not rel.endswith(".txt"):
            raise DictionaryBuildError(f"{where}: 'path' must be a .txt file", file=meta_path)
        path = (ws / rel).resolve()
        if Path(rel).is_absolute() or content not in path.parents:
            raise DictionaryBuildError(
                f"{where}: 'path' must be inside the content directory ({content_dir.name}/)",
                file=meta_path)
        if path in seen:
            raise DictionaryBuildError(f"{where}: path {rel!r} listed twice", file=meta_path)
        seen.add(path)
        url = str(item.get("url") or "").strip()
        parsed = parse_url(url)
        if not parsed:
            raise DictionaryBuildError(
                f"{where} ({rel}): 'url' must be a Google Sheets URL "
                "(https://docs.google.com/spreadsheets/d/<id>/...)", file=meta_path)
        tab = item.get("tab")
        tab = str(tab).strip() if tab is not None else None
        if tab == "":
            raise DictionaryBuildError(f"{where} ({rel}): 'tab' is empty", file=meta_path)
        if parsed[1] is None and tab is None:
            raise DictionaryBuildError(
                f"{where} ({rel}): say which tab: give 'tab' (its name), or a url with "
                "#gid=... (open the tab and copy the address bar)", file=meta_path)
        fetch = item.get("fetch", True)
        if not isinstance(fetch, bool):
            raise DictionaryBuildError(f"{where} ({rel}): 'fetch' must be true or false",
                                       file=meta_path)
        out.append({"path": path, "rel": rel, "url": url, "tab": tab, "fetch": fetch})
    return out


def tidy(rows) -> list:
    """-> rectangular rows of tidied cells, empty trailing rows/columns dropped."""
    def cell(c):
        c = str(c).replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
        return unicodedata.normalize("NFC", c).strip()
    rows = [[cell(c) for c in r] for r in rows]
    while rows and not any(rows[-1]):
        rows.pop()
    if rows:
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        while width and not any(r[width - 1] for r in rows):
            width -= 1
        rows = [r[:width] for r in rows]
    return rows


def to_record_text(rows, url: str, title: str) -> str:
    import record_input
    return record_input.rows_to_text(tidy(rows), comments=[
        "GENERATED by `plan.py sync-sheets` from Google Sheets. Do not edit:",
        "every sync overwrites this file. Edit the sheet instead.",
        f"Sheet: {url}",
        f"Tab: {title}",
    ])


class SheetsClient:
    """Reads tabs through the Sheets API as the service account."""

    def __init__(self):
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
        except ImportError:
            raise DictionaryBuildError("missing libraries: pip install google-auth requests")
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        try:
            if raw:
                info = json.loads(raw)
            elif key_path:
                info = json.loads(Path(key_path).read_text(encoding="utf-8"))
            else:
                raise DictionaryBuildError(
                    "no credentials: set GOOGLE_SERVICE_ACCOUNT_JSON or "
                    "GOOGLE_APPLICATION_CREDENTIALS")
        except (OSError, ValueError) as e:
            raise DictionaryBuildError(f"can't read the service account key: {e}")
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        self.session = AuthorizedSession(creds)
        self.email = info.get("client_email", "the service account")
        self.titles = {}   # spreadsheet id -> {gid: tab title}

    def _get(self, url, **params):
        r = self.session.get(url, params=params, timeout=120)
        if r.status_code in (403, 404):
            raise DictionaryBuildError(
                f"no access (HTTP {r.status_code}); share the spreadsheet with {self.email} "
                "as Viewer, and check the Sheets API is enabled for the key's project")
        r.raise_for_status()
        return r.json()

    def tab_titles(self, sid: str) -> dict:
        """{gid: tab title} for a spreadsheet."""
        if sid not in self.titles:
            meta = self._get(f"{API}/{sid}", fields="sheets.properties(sheetId,title)")
            self.titles[sid] = {t["properties"]["sheetId"]: t["properties"]["title"]
                                for t in meta["sheets"]}
        return self.titles[sid]

    def fetch(self, url: str, tab: str = None):
        """-> (rows, tab title)."""
        sid, gid = parse_url(url)
        title = resolve_tab(self.tab_titles(sid), gid, tab)
        rng = "'" + title.replace("'", "''") + "'"
        data = self._get(f"{API}/{sid}/values/{rng}",
                         valueRenderOption="FORMATTED_VALUE", majorDimension="ROWS")
        return data.get("values", []), title


def resolve_tab(titles: dict, gid, tab) -> str:
    """Picks the tab title from {gid: title} by gid and/or name; with both,
    they must agree."""
    names = ", ".join(repr(t) for t in titles.values())
    if gid is not None:
        if gid not in titles:
            raise DictionaryBuildError(
                f"no tab with gid={gid} in that spreadsheet (deleted or re-created?); "
                f"tabs: {names}")
        if tab is not None and titles[gid] != tab:
            raise DictionaryBuildError(
                f"tab gid={gid} is named {titles[gid]!r}, but the config says 'tab: {tab}' "
                "(renamed in the sheet? update one of them)")
        return titles[gid]
    matches = [t for t in titles.values() if t == tab]
    if not matches:
        raise DictionaryBuildError(f"no tab named {tab!r} in that spreadsheet; tabs: {names}")
    return tab


def validate(path: Path, text: str) -> int:
    """Parses `text` exactly as a build would read the file. Returns the
    number of entries."""
    import record_input
    import transliteration
    return len(record_input.read_record_file(path, text, transliteration.Translator()))


def sync(sheets: list, client=None, log=print) -> list:
    """Downloads, tidies and checks every sheet with fetch: true, then
    writes them all, or nothing if anything failed. Returns the paths
    written (changed files only)."""
    todo = [s for s in sheets if s["fetch"]]
    for s in sheets:
        if not s["fetch"]:
            log(f"kept     {s['rel']} (fetch: false)")
    if not todo:
        return []
    client = client or SheetsClient()

    results, failed = [], []
    for s in todo:
        try:
            rows, title = client.fetch(s["url"], s["tab"])
            text = to_record_text(rows, s["url"], title)
            n = validate(s["path"], text)
            results.append((s, text, f"tab {title!r}, {n} entries"))
        except DictionaryBuildError as e:
            failed.append(f"{s['rel']}: {e}")
        except Exception as e:   # network / API errors
            failed.append(f"{s['rel']}: {type(e).__name__}: {e}")
    if failed:
        raise DictionaryBuildError("sheet sync failed, nothing written:\n  " + "\n  ".join(failed))

    written = []
    for s, text, detail in results:
        p = s["path"]
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != text:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            written.append(p)
        log(f"{'updated ' if old != text else 'same    '} {s['rel']} ({detail})")
    return written
