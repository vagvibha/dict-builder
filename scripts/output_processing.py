#!/usr/bin/python3

class BabylonFormatter:
    """
    Handles serialization of normalized data structures into
    valid, StarDict-compatible .babylon string dictionaries.
    """
    def __init__(self, stats_builder=None):
        self.stats = stats_builder

    def generate_dictionary(self, normalized_entries):
        """
        Transforms a uniform list of entries into a flat Babylon string block.

        Expects normalized_entries to be a dict of file -> list of dicts with:
        - 'words': list of strings (index/lookup words)
        - 'entry': string (the descriptive body or definition)
        """
        if not normalized_entries:
            return ""

        output_cards = []

        for file in normalized_entries:
            for item in normalized_entries[file]:
                words = item.get('words', [])
                body = item.get('entry', '')

                if not words:
                    if self.stats: self.stats.add_malformed_entry(file)
                    continue
                if self.stats: self.stats.add_entry(file, words)

                header = "|".join(words).strip()
                definition = body.strip()

                card = f"{header}\n{definition}\n"
                output_cards.append(card)

        return "\n".join(output_cards) + "\n"


class TabfileFormatter:
    """
    Handles serialization of normalized data structures into
    valid, StarDict-compatible .tsv string dictionaries.
    """
    def __init__(self, stats_builder=None):
        self.stats = stats_builder

    def generate_dictionary(self, normalized_entries):
        """
        Transforms a uniform list of entries into a flat tsv string block.

        Expects normalized_entries to be a dict of file -> list of dicts with:
        - 'words': list of strings (index/lookup words)
        - 'entry': string (the descriptive body or definition)
        """
        if not normalized_entries:
            return ""

        output_cards = []

        for file in normalized_entries:
            for item in normalized_entries[file]:
                words = item.get('words', [])
                body = item.get('entry', '')

                if not words:
                    if self.stats: self.stats.add_malformed_entry(file)
                    continue
                if self.stats: self.stats.add_entry(file, words)

                header = "|".join(words).strip()
                definition = body.strip()

                card = f"{header}\t{definition}\n"
                output_cards.append(card)

        return "\n".join(output_cards)
