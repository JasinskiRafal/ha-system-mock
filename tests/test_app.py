import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from counter import Counter, run_counter


class CounterTest(unittest.TestCase):
    def test_counter_survives_reopening_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'counter.db'
            counter = Counter(path)
            self.assertEqual(counter.value(), 0)
            counter.increment()
            self.assertEqual(Counter(path).value(), 1)

    def test_automatic_counter_increments_and_persists_without_a_client(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'counter.db'
            counter = Counter(path)
            stop = threading.Event()
            worker = threading.Thread(target=run_counter, args=(counter, stop))
            worker.start()
            try:
                self.assertFalse(stop.wait(1.25))
            finally:
                stop.set()
                worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(Counter(path).value(), 2)

    def test_concurrent_increments_are_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            counter = Counter(Path(directory) / 'counter.db')
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: counter.increment(), range(40)))
            self.assertEqual(counter.value(), 40)

if __name__ == '__main__':
    unittest.main()
