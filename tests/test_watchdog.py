"""Tests for snippets/watchdog.py — heartbeat timeout monitor."""

import threading
import time
import unittest

from snippets.watchdog import Watchdog


class TestWatchdogBasics(unittest.TestCase):
    """Core start / pet / stop behaviour."""

    def test_start_and_stop(self):
        wd = Watchdog(timeout=1.0, on_bark=lambda: None)
        wd.start()
        self.assertTrue(wd.is_alive)
        wd.stop()
        self.assertFalse(wd.is_alive)

    def test_start_idempotent(self):
        wd = Watchdog(timeout=1.0, on_bark=lambda: None)
        wd.start()
        wd.start()  # should not raise or create a second thread
        self.assertTrue(wd.is_alive)
        wd.stop()

    def test_pet_resets_timer(self):
        """Petting within the timeout window prevents barking."""
        barked = []
        wd = Watchdog(timeout=0.2, on_bark=lambda: barked.append(True))
        wd.start()
        for _ in range(5):
            time.sleep(0.1)
            wd.pet()
        wd.stop()
        self.assertEqual(barked, [])

    def test_bark_on_timeout(self):
        """Dog barks when no pet arrives within the timeout."""
        barked = []
        wd = Watchdog(timeout=0.1, on_bark=lambda: barked.append(True))
        wd.start()
        time.sleep(0.35)
        wd.stop()
        self.assertTrue(wd.barked)
        self.assertGreaterEqual(len(barked), 1)

    def test_elapsed_grows_without_pet(self):
        wd = Watchdog(timeout=5.0, on_bark=lambda: None)
        wd.start()
        time.sleep(0.1)
        self.assertGreater(wd.elapsed, 0.05)
        wd.stop()


class TestWatchdogRepeat(unittest.TestCase):
    """repeat=True keeps barking; repeat=False fires once."""

    def test_single_fire_by_default(self):
        count = []
        wd = Watchdog(timeout=0.1, on_bark=lambda: count.append(1))
        wd.start()
        time.sleep(0.5)
        wd.stop()
        self.assertEqual(len(count), 1)

    def test_repeat_mode_barks_multiple(self):
        count = []
        wd = Watchdog(
            timeout=0.1, on_bark=lambda: count.append(1), repeat=True
        )
        wd.start()
        time.sleep(0.55)
        wd.stop()
        self.assertGreaterEqual(len(count), 3)


class TestWatchdogEdgeCases(unittest.TestCase):
    """Boundary conditions and error resilience."""

    def test_invalid_timeout(self):
        with self.assertRaises(ValueError):
            Watchdog(timeout=0, on_bark=lambda: None)
        with self.assertRaises(ValueError):
            Watchdog(timeout=-1, on_bark=lambda: None)

    def test_callback_exception_does_not_crash(self):
        """Even if on_bark raises, the watchdog stays alive (repeat mode)."""

        def bad_callback():
            raise RuntimeError("boom")

        wd = Watchdog(timeout=0.1, on_bark=bad_callback, repeat=True)
        wd.start()
        time.sleep(0.35)
        self.assertTrue(wd.is_alive)
        wd.stop()

    def test_pet_from_another_thread(self):
        """pet() is thread-safe."""
        barked = []
        wd = Watchdog(timeout=0.2, on_bark=lambda: barked.append(True))
        wd.start()

        def petter():
            for _ in range(10):
                wd.pet()
                time.sleep(0.05)

        t = threading.Thread(target=petter)
        t.start()
        t.join()
        wd.stop()
        self.assertEqual(barked, [])

    def test_stop_without_start(self):
        """stop() on a never-started watchdog should not raise."""
        wd = Watchdog(timeout=1.0, on_bark=lambda: None)
        wd.stop()  # should be a no-op

    def test_barked_property_false_initially(self):
        wd = Watchdog(timeout=1.0, on_bark=lambda: None)
        self.assertFalse(wd.barked)


class TestWatchdogStopResponsiveness(unittest.TestCase):
    """stop() should return promptly, not block for the full timeout."""

    def test_stop_is_fast(self):
        wd = Watchdog(timeout=10.0, on_bark=lambda: None)
        wd.start()
        t0 = time.monotonic()
        wd.stop()
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
