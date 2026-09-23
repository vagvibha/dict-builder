import unittest

from tests import helpers  # noqa: F401
from output_processing import BabylonFormatter, TabfileFormatter
from stats import FileStats, StatsBuilder


class TestFileStats(unittest.TestCase):
    def test_initial(self):
        self.assertEqual(FileStats().get_stats(), (0, 0, 0, {}))

    def test_entries_and_malformed(self):
        s = FileStats()
        s.add_entry(["a", "b", "c"])
        s.add_malformed_entry()
        self.assertEqual(s.get_stats(), (2, 3, 1, {}))

    def test_frequency(self):
        s = FileStats(track_frequency=True)
        s.add_entry(["big", "large"])
        s.add_entry(["big", "huge"])
        self.assertEqual(s.get_stats(supply_top_entries=1)[3], {"big": 2})
        self.assertEqual(FileStats().get_stats(supply_top_entries=1)[3], {})

    def test_dump_formatted(self):
        s = FileStats()
        s.add_entry(["a", "b"])
        s.add_malformed_entry()
        out = s.dump_formatted(prefix="")
        self.assertIn("Total Entries: 2", out)
        self.assertIn("Total Words: 2", out)
        self.assertIn("Malformed Entries: 1", out)


class TestStatsBuilder(unittest.TestCase):
    def test_per_file_isolation(self):
        b = StatsBuilder()
        b.add_entry("A", ["x", "y"])
        b.add_entry("A", ["z"])
        b.add_malformed_entry("A")
        b.add_entry("B", ["w"])
        self.assertEqual(b.get_full_stats(), {"A": (3, 3, 1, {}), "B": (1, 1, 0, {})})

    def test_unseen_file(self):
        self.assertEqual(StatsBuilder().get_stats("new"), (0, 0, 0, {}))

    def test_frequency_propagates(self):
        b = StatsBuilder(track_frequency=True)
        b.add_entry("f", ["a", "a", "b"])
        self.assertEqual(b.get_stats("f", supply_top_entries=2)[3], {"a": 2, "b": 1})

    def test_dump_all(self):
        b = StatsBuilder()
        b.add_entry("alpha.txt", ["one"])
        b.add_entry("beta.txt", ["two", "three"])
        out = b.dump_all_files_formatted(prefix="")
        self.assertIn("File: alpha.txt", out)
        self.assertIn("File: beta.txt", out)
        self.assertIn("Total Words: 2", out)


class TestFormatters(unittest.TestCase):
    DATA = {
        "f1.txt": [{'words': ['a', 'b'], 'entry': ' body1 '},
                   {'words': [], 'entry': 'dropped'}],
        "f2.txt": [{'words': ['c'], 'entry': 'body2'}],
    }

    def test_tabfile(self):
        stats = StatsBuilder()
        out = TabfileFormatter(stats).generate_dictionary(self.DATA)
        self.assertEqual(out, "a|b\tbody1\n\nc\tbody2\n")
        self.assertEqual(stats.get_full_stats(),
                         {"f1.txt": (2, 2, 1, {}), "f2.txt": (1, 1, 0, {})})

    def test_babylon(self):
        out = BabylonFormatter().generate_dictionary(self.DATA)
        self.assertEqual(out, "a|b\nbody1\n\nc\nbody2\n\n")

    def test_empty(self):
        self.assertEqual(TabfileFormatter().generate_dictionary({}), "")
        self.assertEqual(BabylonFormatter().generate_dictionary({}), "")


if __name__ == "__main__":
    unittest.main()
