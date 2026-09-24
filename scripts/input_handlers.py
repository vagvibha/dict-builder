import re

import utils
from utils import KNOWN_TYPES
from errors import DictionaryBuildError, UnmappedCharacterError
from markup import strip_bold_tags
import transliteration


class HandlerFactory:
    KNOWN_TYPES = KNOWN_TYPES

    @staticmethod
    def getInputHandler(type_name, translator=None, exclusion_list=None, info=None):
        defaultTranslator = transliteration.Translator()

        if translator is None:
            translator = defaultTranslator
        if exclusion_list is None:
            exclusion_list = utils.load_global_exclusions()

        if type_name == 'one-liner':
            return DictionaryInputHandler(translator, exclusion_list, info)
        elif type_name == 'shloka':
            return ShlokaInputHandler(translator, exclusion_list, info)
        elif type_name == 'notes':
            return NotesInputHandler(translator, exclusion_list, info)
        else:
            raise DictionaryBuildError(
                f"unknown type '{type_name}' (expected one of {sorted(KNOWN_TYPES)})",
                file=info)


class BaseInputHandler:
    def __init__(self, translator=None, exclusion_list=None, info=None):
        self.translator = translator
        self.exclusion_list = set(exclusion_list) if exclusion_list else set()
        self.source = "unknown"
        self.add_words_to_record = True
        self.filename = info

    # --- Subclass Implementation Hooks ---

    def split_records(self, raw_content: str) -> list:
        """Hook: returns a list of (line_no, record_text) tuples, line_no
        being 1-based and relative to the start of raw_content."""
        raise NotImplementedError()

    def extract_record_parts(self, headers: dict, record: str) -> tuple:
        """
        Hook: Subclasses must parse a single record block.
        Returns: tuple of (list_of_raw_keywords, str_entry_body)
        """
        raise NotImplementedError()

    # --- Common Shared Invariants ---
    def dedup_tokens(self, tokens: list, exclude_list: list = None) -> list:
        """Dedup tokens and optionally exclude some tokens"""
        seen_lower = set()
        cleaned_list = []

        for token in tokens:
            if not token:
                continue

            stripped = token.strip()
            token_lower = stripped.lower()

            if exclude_list and token in exclude_list:
                continue

            if token_lower not in seen_lower:
                seen_lower.add(token_lower)
                cleaned_list.append(stripped)

        return cleaned_list

    def clean_tokens(self, raw_tokens: list) -> list:
        """Universal token cleanup: removes digits, duplicates, and preserves order."""
        cleaned_list = []

        tokens = self.dedup_tokens(raw_tokens, self.exclusion_list)
        for token in tokens:
            # Drop pure numeric tokens
            if re.match(r'^[\d\u0966-\u096F\s]+$', token):
                continue

            cleaned_list.append(token)

        return cleaned_list

    # --- The Invariant Template Pipeline ---

    def process_stream(self, raw_content: str, headers: dict = None, line_offset: int = 0) -> list:
        """
        The uniform stream processing engine inherited by all handlers.
        Orchestrates split, extraction, translation, and cleanup polymorphically.

        line_offset is the number of lines already consumed before
        raw_content started (e.g. the file's HEADER: block), so error
        messages can report an absolute line number within the file.
        """
        if headers is None:
            headers = {}
        if 'skip' in headers:
            self.exclusion_list.update(headers['skip'])
        self.source = 'unknown'
        if 'title' in headers:
            self.source = headers['title']
        suffix = True
        if 'lang' in headers and headers['lang'] == 'en':
            suffix = False

        if not raw_content or not raw_content.strip():
            return []

        # 1. Common Orchestration: Split the stream using subclass strategy
        records = self.split_records(raw_content)
        processed_output = []

        for line_no, record in records:
            abs_line = line_no + line_offset
            if not record.strip():
                continue

            try:
                raw_keywords, entry_body = self.extract_record_parts(headers, record)
            except DictionaryBuildError as e:
                raise e.with_location(file=self.filename, line=abs_line)
            except ValueError as e:
                raise DictionaryBuildError(str(e), file=self.filename, line=abs_line) from e

            if not raw_keywords:
                continue

            # Apply common cleanup policies including dedup, exclusions, etc.
            # The order of words as encountered is retained.
            cleaned_keywords = self.clean_tokens(raw_keywords)

            # Translate to iTrans
            try:
                translated_words = self.translator.translateWords(cleaned_keywords, suffix=suffix)
            except UnmappedCharacterError as e:
                raise DictionaryBuildError(e.message, file=self.filename, line=abs_line) from e

            # Words are optionally appended to entry (so the others can
            #     be seen during viewing - mainly to see if another hint should
            #     have been added)
            words_string = "; ".join(cleaned_keywords)

            # Clean again after translation (it can introduce case-based dupes)
            translated_words = self.clean_tokens(translated_words)

            # This step is only needed for parity with legacy. Can be
            # removed after migration. This only impacts the order in
            # which the words appear in babylon file
            translated_words.sort()

            # In cases of shlokas, we don't append them, let subclass decide.
            if self.add_words_to_record:
                final_entry = entry_body + f"<br>{words_string}<br>[{self.source}]"
            else:
                final_entry = entry_body + f"<br>[{self.source}]"

            if cleaned_keywords:
                processed_output.append({
                    'words': translated_words,
                    'entry': final_entry
                })

        return processed_output


class DictionaryInputHandler(BaseInputHandler):
    """The 'one-liner' input format: each '- ' line is one record, with
    lookup keys given inline as '((key1;key2))'."""

    def __init__(self, translator=None, exclusion_list=None, info=None):
        # Dictionary uses specifically requested tokens. Don't exclude anything!
        super().__init__(translator, exclusion_list=[], info=info)
        self.parenthesis_pattern = re.compile(r'\(\(([^)]*)\)\)')

    def split_records(self, raw_content: str) -> list:
        return utils.enumerate_nonblank_lines(raw_content)

    def extract_record_parts(self, headers: dict, record: str) -> tuple:
        """
        Returns: tuple of (list_of_raw_keywords, str_entry_body)
        """
        if not record or record.startswith('#') or not record.strip():
            return None, None

        # Parse source indicators
        if 'title' not in headers and not record.startswith('- '):
            source_match = re.findall(r'\[([^]]*)\]', record)
            if source_match:
                # Update source (until new source is explicitly encountered)
                self.source = "; ".join(source_match)
                return None, None

        if not record.startswith('- '):
            raise ValueError(f"bad record - does not start with '- ' marker: {record!r}")

        # Strip the '- ' record prefix marker
        working_text = record[2:]
        main_words = []
        # Find keywords indicated in parenthesis
        syn_words = self.parenthesis_pattern.findall(working_text)
        if syn_words:
            extracted_syns = []
            for w in syn_words:
                # Drop empty words (e.g. '(w1;)' or '(w1;;w2)'
                extracted_syns.extend([token.strip()
                                        for token in w.split(';')
                                        if token.strip()])
            main_words.extend(extracted_syns)

        # Nothing on this line... e.g. this may be here just for flashcards, ignore.
        if not main_words:
            return None, None

        # Apply content cutoff rule
        valid_offsets = [idx for idx in (working_text.find('{{'), working_text.find('((')) if idx != -1]
        if valid_offsets:
            working_text = working_text[:min(valid_offsets)]

        cleaned_entry = working_text.strip()
        cleaned_main_words = [w.strip() for w in main_words if w.strip()]

        return cleaned_main_words, cleaned_entry


class NotesInputHandler(BaseInputHandler):
    """The 'notes' input format: multi-line records, each starting with
    '- key1;key2' on its own line, everything after is free-form notes."""

    def __init__(self, translator=None, exclusion_list=None, info=None):
        # Notes use specifically requested tokens. Don't exclude anything!
        super().__init__(translator, exclusion_list=[], info=info)

    def split_records(self, raw_content: str) -> list:
        return utils.split_with_line_numbers(raw_content, '\n-')

    def extract_record_parts(self, headers, record: str) -> tuple:
        if '\n' in record:
            words_line, raw_notes = record.split('\n', 1)
        else:
            words_line = record
            raw_notes = ""

        if "title" in headers and headers["title"]:
            self.source = headers["title"]

        words_line = words_line.strip(' -')
        raw_tokens = [w.strip() for w in words_line.split(';') if w.strip()]
        formatted_notes = raw_notes.replace('\n', '<br>')

        return raw_tokens, f"<br>{formatted_notes}"


class ShlokaInputHandler(BaseInputHandler):
    """The 'shloka' input format: blank-line separated records, each a
    verse optionally followed by '====' and notes. Index keys are
    auto-derived from the verse text unless overridden/excluded."""

    def __init__(self, translator, exclusion_list=None, info=None):
        super().__init__(translator, exclusion_list, info=info)
        self.add_words_to_record = False

    def split_records(self, raw_content: str) -> list:
        return utils.split_with_line_numbers(raw_content, '\n\n')

    # Punctuation that is never part of a lookup word. It is treated as a
    # word separator wherever it appears (standalone, or at the start /
    # middle / end of a word).
    PUNCTUATION = ',.।?॥;:!|\'"‘’“”[]{}'
    _PUNCT_RE = re.compile('[' + re.escape(PUNCTUATION) + ']')
    _PAREN_RE = re.compile(r'\([^()]*\)')
    # Verse numbers / separators left over once punctuation is removed.
    _VERSE_NUM_RE = re.compile(r"^[०१२३४५६७८९0-9\-]+$")

    def tokenize_text(self, raw_text: str) -> list:
        """Splits verse-like text into lookup words, dropping punctuation
        and pure verse-number tokens."""
        # A bolded word would otherwise glue "<b>"/"</b>" onto the token
        # with no whitespace to split on - strip those back out first.
        text = strip_bold_tags(raw_text)
        text = self._PUNCT_RE.sub(' ', text)
        return [tok for tok in text.split() if not self._VERSE_NUM_RE.match(tok)]

    def extract_shloka_tokens(self, raw_shloka: str) -> list:
        return self.tokenize_text(raw_shloka)

    def extract_double_plus_tokens(self, text: str) -> list:
        """'++ ' line: anything in (parentheses) is ignored, then tokenized
        like the verse itself."""
        # Loop to handle nested parentheses from the inside out.
        prev = None
        while prev != text:
            prev, text = text, self._PAREN_RE.sub(' ', text)
        # Any unbalanced leftovers are just dropped.
        text = text.replace('(', ' ').replace(')', ' ')
        return self.tokenize_text(text)

    def extract_record_parts(self, headers: dict, record: str) -> tuple:
        if not record or not record.strip():
            return None, None

        headers = headers or {}

        parts = record.split('\n====\n')
        if len(parts) == 1:
            # make sure to strip ==== from the end
            raw_shloka = re.sub(r"====\s*\Z", "", parts[0]).strip()
        else:
            raw_shloka = parts[0].strip()

        notes_payload = parts[1].strip() if len(parts) > 1 else ""
        # strip all trailing blank lines
        notes_payload = re.sub(r"(\s*\n)*\s*\Z", "", notes_payload)

        excluded_words = []
        additional_tokens = []
        non_meta_notes = []

        exclude_all_derived = False
        ignore_shloka_key = False
        has_double_plus = False
        # HEADER:show_anvaya=false: '++ ' lines still supply keys but are
        # left out of the entry (like '+ ' lines).
        show_anvaya = headers.get('show_anvaya', True)

        # get notes, and any additional words
        for note in notes_payload.split('\n'):
            note = note.strip()
            if not note:
                # preserve empty lines
                non_meta_notes.append(note)
                continue
            if note[0:2] == "- ":
                excluded_words.extend([word.strip()
                                        for word in note[2:].split(';') if word.strip()])
                if 'all' in excluded_words:
                    exclude_all_derived = True
                    excluded_words.remove('all')
                if 'nokey' in excluded_words:
                    ignore_shloka_key = True
                    excluded_words.remove('nokey')
            elif note[0:3] == '++ ':
                has_double_plus = True
                if show_anvaya:
                    non_meta_notes.append(note)
                additional_tokens.extend(self.extract_double_plus_tokens(note[3:]))
            elif note[0:2] == "+ ":
                additional_tokens.extend([word.strip()
                                           for word in note[2:].split(';')
                                           if word.strip()])
            else:
                non_meta_notes.append(note)

        # HEADER:auto_shloka=false turns off deriving keys from the verse
        # text; only '+ ' and '++ ' lines supply them.
        auto_shloka = headers.get('auto_shloka', True)

        raw_shloka_tokens = []
        if auto_shloka and not exclude_all_derived and not has_double_plus:
            raw_shloka_tokens = self.extract_shloka_tokens(raw_shloka)

        if 'shlokakey' in headers and not ignore_shloka_key:
            self.create_shloka_ref(raw_shloka, headers['shlokakey'], additional_tokens)

        tokens = raw_shloka_tokens + additional_tokens

        # Since shlokas has it's own exclusion mechanism per shloka,
        # dedup and exclude
        final_tokens = self.dedup_tokens(tokens, excluded_words)

        formatted_record = raw_shloka.replace('\n', '<br>')
        if notes_payload and non_meta_notes:
            formatted_record = f"{formatted_record}<br>====<br>{'<br>'.join(non_meta_notes)}"
        return final_tokens, formatted_record

    def extract_shloka_ref(self, shloka_text):
        """Locates text within last double dandas (॥) and extracts numbers."""
        matches = re.findall(r'॥\s*([0-9०१२३४५६७८९\-।\.]+?)\s*॥\s*\Z', shloka_text)
        if not matches:
            return []

        raw_num_block = matches[-1]
        parts = re.split(r'[-.\/।|]', raw_num_block)
        return [p.strip() for p in parts if p.strip()]

    def create_shloka_ref(self, shloka_text, shloka_config, additional_tokens):
        """Builds a zero-padded structural key signature."""
        key_config = shloka_config.split(',')
        padding_rules = [int(p.strip()) for p in key_config[1:]]

        shloka_ref = self.extract_shloka_ref(shloka_text)
        if not shloka_ref:
            return None

        if len(shloka_ref) != len(padding_rules):
            raise ValueError(
                f"mismatched shlokakey structural depth. Configuration '{shloka_config}' "
                f"expects {len(padding_rules)} tiers, but found {len(shloka_ref)} parts "
                f"in verse marker: {shloka_ref}"
            )

        # Add prefix 'e:' to avoid adding (eng) suffix (e.g. we want 'BG-01-23')
        prefix = key_config[0].strip()
        ref_pieces = ["e:" + prefix]
        for idx, pad_len in enumerate(padding_rules):
            try:
                translated_num = self.translator.translateWord(shloka_ref[idx], suffix=False)
                int_val = int(translated_num)
                ref_pieces.append(f"{int_val:0{pad_len}d}")
            except (ValueError, TypeError, IndexError):
                return None  # Fail safely if mapping numbers breaks

        additional_tokens.append("-".join(ref_pieces))
