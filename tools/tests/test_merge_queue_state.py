"""`tools/merge_queue/state.py`: one queue at a time, and a memory that outlives it."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.merge_queue.state import Held, Memory, acquire

NOW = datetime(2026, 10, 1, tzinfo=UTC)


class Lock(unittest.TestCase):
    def test_a_second_queue_is_refused_naming_the_first(self) -> None:
        with tempfile.TemporaryDirectory() as place:
            path = Path(place) / "lock"
            held = acquire(path)
            with self.assertRaises(Held) as refused:
                acquire(path)
            self.assertIn("already running", str(refused.exception))
            held.close()
            acquire(path).close()  # freed with the process (here, the file)


class TheMemory(unittest.TestCase):
    def test_it_outlives_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as place:
            path = Path(place) / "state.json"
            memory = Memory(path)
            memory.seen(1, "a", NOW)
            memory.passed_over([1])
            memory.reruns.add(7)
            memory.save()
            again = Memory(path)
            self.assertEqual(again.first_seen["1"]["head"], "a")
            self.assertEqual((again.passes, again.reruns), ({"1": 1}, {7}))

    def test_a_new_head_restarts_its_clock_but_not_its_place(self) -> None:
        memory = Memory(None)
        memory.seen(1, "a", NOW)
        later = NOW.replace(hour=1)
        entry = memory.seen(1, "b", later)
        self.assertEqual((entry["line"], entry["at"]), (NOW.isoformat(), later.isoformat()))

    def test_a_hand_back_is_news_once_per_head_and_reason(self) -> None:
        memory = Memory(None)
        self.assertTrue(memory.first_time(1, "a", "red"))
        self.assertFalse(memory.first_time(1, "a", "red"))
        self.assertTrue(memory.first_time(1, "b", "red"))

    def test_an_unreadable_file_is_an_empty_memory(self) -> None:
        with tempfile.TemporaryDirectory() as place:
            path = Path(place) / "state.json"
            path.write_text("{not json")
            self.assertEqual(Memory(path).first_seen, {})


if __name__ == "__main__":
    unittest.main()
