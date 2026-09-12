import sys
import tempfile
import unittest

from app.execution.bounded_process import BoundedProcessError, run_bounded_process


class BoundedProcessTests(unittest.TestCase):
    def test_large_stdout_is_drained_without_unbounded_parent_buffer(self):
        result = run_bounded_process(
            [sys.executable, "-c", "print('x' * 10000000)"],
            cwd=tempfile.gettempdir(),
            env={"PATH": __import__("os").environ.get("PATH", "")},
            timeout=10,
            max_output_bytes=1024,
        )
        self.assertFalse(result.timed_out)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout), 1025)
        self.assertGreater(len(result.stdout), 1024)

    def test_timeout_kills_process_group_while_draining_output(self):
        code = "import time\nwhile True:\n    print('x' * 4096)\n    time.sleep(0.001)"
        result = run_bounded_process(
            [sys.executable, "-c", code],
            cwd=tempfile.gettempdir(),
            env={"PATH": __import__("os").environ.get("PATH", "")},
            timeout=1,
            max_output_bytes=1024,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout.__len__(), 1025)

    def test_empty_command_is_rejected(self):
        with self.assertRaises(ValueError):
            run_bounded_process(
                [],
                cwd=tempfile.gettempdir(),
                env={},
                timeout=1,
                max_output_bytes=1024,
            )


if __name__ == "__main__":
    unittest.main()
