from collections import defaultdict, Counter

class FileStats:

    def __init__(self, track_frequency: bool = False):
        """Initializes the FileStats.

        :param track_frequency: Whether to keep track of the individual frequency of words.
        """
        self.track_frequency = track_frequency

        # Internal counters
        self.n_entries = 0
        self.n_synonyms = 0
        self.n_malformed = 0

        # Dictionary to store unique words across all entries
        self.dictionary = {}

        # Counter for word frequencies (only populated if track_frequency=True)
        self.word_frequencies = Counter()

    def add_entry(self, words: list[str]) -> None:
        """Supplies a list of synonyms that are being added to the dictionary
        for one entry.

        :param words: A list of synonymous strings.
        """
        self.n_entries += 1
        self.n_synonyms += len(words)

        # Build/update the internal dictionary mapping
        for word in words:
            if word not in self.dictionary:
                self.dictionary[word] = set()

            synonyms_to_add = {w for w in words if w != word}
            self.dictionary[word].update(synonyms_to_add)

        # Track frequencies if enabled
        if self.track_frequency:
            self.word_frequencies.update(words)

    def add_malformed_entry(self) -> None:
        """Indicates that a malformed entry was encountered.

        Increments both the total entries counter and the malformed counter.
        """
        self.n_entries += 1
        self.n_malformed += 1

    def get_stats(
        self, supply_top_entries: int = 0
    ) -> tuple[int, int, int, dict[str, int]]:
        """Returns the accumulated statistics.

        :param supply_top_entries: The number of top frequent words to return.
        :return: A tuple of (n_entries, n_synonyms, n_malformed, top_entries)
        """
        top_entries = {}

        if supply_top_entries > 0 and self.track_frequency:
            top_entries = dict(self.word_frequencies.most_common(supply_top_entries))

        return (self.n_entries, self.n_synonyms, self.n_malformed, top_entries)

    def dump_formatted(self, prefix = '\t', supply_top_entries = 0) -> str:
        formatted_data = f"{prefix}Total Entries: {self.n_entries}\n"\
            f"{prefix}Total Words: {self.n_synonyms}"
        if self.n_malformed:
            formatted_data += f"\n{prefix}Malformed Entries: {self.n_malformed}"
        if supply_top_entries > 0 and self.track_frequency and len(self.word_frequencies):
            top_entries = dict(self.word_frequencies.most_common(supply_top_entries))
            formatted_data += f"\n{prefix}Most frequent words:\n"
            for word, freq in top_entries.items():
                formatted_data += f"{prefix}\t{word}\t: {freq}\n"
        return formatted_data


class StatsBuilder:
    """Manages statistics across multiple isolated input files."""

    def __init__(self, track_frequency: bool = False):
        """Initializes the StatsBuilder."""
        self.track_frequency = track_frequency

        # Maps input_file (str) -> FileStats instance
        # Using a lambda ensures every new file automatically gets its own FileStats setup
        self.files = defaultdict(lambda: FileStats(track_frequency=self.track_frequency))

    def add_entry(self, input_file: str, words: list[str]) -> None:
        """Supplies a list of synonyms for one entry in a specific file."""
        self.files[input_file].add_entry(words)

    def add_malformed_entry(self, input_file: str) -> None:
        """Indicates that a malformed entry was encountered in a specific file."""
        self.files[input_file].add_malformed_entry()

    def get_stats(
        self, input_file: str, supply_top_entries: int = 0
    ) -> tuple[int, int, int, dict[str, int]]:
        """Returns the accumulated statistics for a specific file."""
        return self.files[input_file].get_stats(supply_top_entries)

    def get_full_stats(self, supply_top_entries: int = 0) -> dict[str, tuple[int, int, int, dict[str, int]]]:
        """Returns the accumulated statistics for all managed files.
        :return: A dictionary mapping input file names to their respective stats tuple:
                 { file_name: (n_entries, n_synonyms, n_malformed, top_entries) }
        """
        return {
            file_name: stats_obj.get_stats(supply_top_entries)
            for file_name, stats_obj in self.files.items()
        }

    def dump_formatted(self, input_file: str, prefix='\t', supply_top_entries=0) -> str:
        """Returns a formatted string of stats for a specific file."""
        return self.files[input_file].dump_formatted(prefix, supply_top_entries)

    def dump_all_files_formatted(self, prefix='\t', supply_top_entries=0) -> str:
        """Helper method to print out stats for every file tracked so far."""
        output = []
        for file_name, stats in self.files.items():
            output.append(f"File: {file_name}")
            output.append(stats.dump_formatted(prefix=prefix, supply_top_entries=supply_top_entries))
        return "\n".join(output)
