"""Trusted temporary process probes; no project code, network or model calls."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_company.processes import ProcessError, capture


class BoundedProcessTests(unittest.TestCase):
    def run_python(self, code, **kwargs):
        return capture([sys.executable, "-I", "-B", "-c", code], env={"PATH": "/usr/bin:/bin"}, **kwargs)

    def test_binary_stdin_and_separate_output_streams(self):
        result = self.run_python("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stderr.buffer.write(b'error')", input_bytes=b"\x00\xfffixture", timeout=2)
        self.assertEqual(result, (0, b"\x00\xfffixture", b"error"))

    def test_combined_stream_limit(self):
        with self.assertRaisesRegex(ProcessError, "output limit"):
            self.run_python("import os; os.write(1,b'x'*600); os.write(2,b'y'*600)", max_output=1000, timeout=2)

    def test_timeout_after_pipes_close(self):
        started = time.monotonic()
        with self.assertRaisesRegex(ProcessError, "timed out"):
            self.run_python("import os,time; os.close(1); os.close(2); time.sleep(5)", timeout=0.15)
        self.assertLess(time.monotonic() - started, 2)

    def test_cancel_after_pipes_close(self):
        started = time.monotonic()
        with self.assertRaisesRegex(ProcessError, "cancelled"):
            self.run_python("import os,time; os.close(1); os.close(2); time.sleep(5)", timeout=2,
                            cancel=lambda: time.monotonic() - started > 0.15)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_stdin_backpressure_does_not_defeat_deadline(self):
        started = time.monotonic()
        with self.assertRaisesRegex(ProcessError, "timed out"):
            self.run_python("import time; time.sleep(5)", input_bytes=b"x" * 65536, timeout=0.15)
        self.assertLess(time.monotonic() - started, 2)

    def test_timeout_cleans_up_descendants(self):
        with tempfile.TemporaryDirectory(prefix="company-process-test-") as directory:
            marker = Path(directory) / "survived"
            child = "import pathlib,time; time.sleep(0.5); pathlib.Path(" + repr(str(marker)) + ").write_text('late')"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-I','-B','-c'," + repr(child) + "]); time.sleep(5)"
            with self.assertRaisesRegex(ProcessError, "timed out"):
                self.run_python(parent, timeout=0.15)
            time.sleep(0.6)
            self.assertFalse(marker.exists())

    def test_invalid_bounds_and_precancel_never_launch(self):
        with patch("agent_company.processes.subprocess.Popen") as launch:
            for args in ({"timeout": 0}, {"timeout": float("nan")}, {"timeout": float("inf")},
                         {"max_output": 0}, {"input_bytes": b"x" * 65537}, {"cancel": lambda: True}):
                with self.subTest(args=list(args)), self.assertRaises(ProcessError):
                    capture(["not-run"], env={}, **args)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
