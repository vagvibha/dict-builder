"""Shared test helpers. Importing this puts scripts/ on sys.path."""
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def have_stardict_tools() -> bool:
    """True if PyGlossary and dictzip are available (needed for the
    StarDict-producing integration tests)."""
    try:
        import pyglossary  # noqa: F401
    except Exception:
        return False
    return shutil.which("dictzip") is not None or Path("/opt/homebrew/bin/dictzip").exists()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class PassthroughTranslator:
    """Stands in for transliteration.Translator: returns words unchanged,
    so handler tests can assert on the raw tokens."""

    def translateWords(self, words, suffix=True):
        return [w for w in words if w]

    def translateWord(self, word, suffix=True):
        return word
