"""Canonical tests with fresh native reports; neither tests nor reports are a sandbox.

Keep runner discovery configuration (including native filename patterns), while
discarding inherited selection options and pytest addopts for acceptance runs.
Reports establish what the runner reported, not proof against dishonest project code.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def test_environment(env: dict[str, str]) -> dict[str, str]:
    """Make acceptance independent of inherited collection/filtering shortcuts."""
    cleaned = {
        key: value for key, value in env.items()
        if not key.startswith(("PYTEST_", "VITEST_"))
        and not key.startswith("PYTHON")
        and key not in {"NODE_OPTIONS", "NODE_ENV", "__PYVENV_LAUNCHER__"}
    }
    cleaned.update({"CI": "true", "NODE_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"})
    return cleaned


def _read_report(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Test runner did not create a fresh regular result report.")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Cannot read test result report: {error}") from error


def _counter(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Malformed test report: {label} must be a nonnegative integer.")
    return value


def vitest_passes(path: Path) -> int:
    """Count actual assertion results, checking the JSON reporter's totals too."""
    try:
        report = json.loads(_read_report(path))
    except json.JSONDecodeError as error:
        raise ValueError("Malformed Vitest JSON result report.") from error
    if not isinstance(report, dict) or report.get("success") is not True:
        raise ValueError("Vitest did not report a successful completed run.")
    counts = {key: _counter(report.get(key), key) for key in (
        "numTotalTests", "numPassedTests", "numFailedTests", "numFailedTestSuites"
    )}
    if counts["numFailedTests"] or counts["numFailedTestSuites"]:
        raise ValueError("Vitest reported failing tests or suites.")
    suites = report.get("testResults")
    if not isinstance(suites, list):
        raise ValueError("Malformed Vitest report: testResults must be a list.")
    passed = total = 0
    for suite in suites:
        if not isinstance(suite, dict) or suite.get("status") != "passed":
            raise ValueError("Vitest reported a failed or incomplete test file.")
        assertions = suite.get("assertionResults")
        if not isinstance(assertions, list):
            raise ValueError("Malformed Vitest report: assertionResults must be a list.")
        for assertion in assertions:
            if not isinstance(assertion, dict):
                raise ValueError("Malformed Vitest assertion result.")
            status = assertion.get("status")
            if status not in {"passed", "skipped", "todo"}:
                raise ValueError("Vitest reported a failed, pending, or unknown assertion.")
            failures = assertion.get("failureMessages")
            if failures not in (None, []):
                raise ValueError("Vitest assertion contains failure messages.")
            total += 1
            passed += status == "passed"
    if total != counts["numTotalTests"] or passed != counts["numPassedTests"]:
        raise ValueError("Malformed Vitest report: assertion results disagree with totals.")
    if passed < 1:
        raise ValueError("No tests actually passed; an empty or all-skipped run is not acceptance.")
    return passed


def pytest_passes(path: Path) -> int:
    """Skipped and xfailed JUnit cases cannot satisfy the executed-test gate."""
    try:
        report = ET.fromstring(_read_report(path))
    except ET.ParseError as error:
        raise ValueError("Malformed pytest JUnit result report.") from error
    if report.tag not in {"testsuites", "testsuite"}:
        raise ValueError("Malformed pytest report: expected testsuite(s).")
    suites = [report] if report.tag == "testsuite" else list(report.findall("testsuite"))
    if not suites or list(report.iter("failure")) or list(report.iter("error")):
        raise ValueError("Pytest report has no suites or contains failures/errors.")
    passed = 0
    for suite in suites:
        counts = {}
        for key in ("tests", "failures", "errors", "skipped"):
            value = suite.get(key, "")
            if not value.isascii() or not value.isdecimal():
                raise ValueError(f"Malformed pytest report: invalid {key} counter.")
            counts[key] = int(value)
        cases = list(suite.findall("testcase"))
        skipped = sum(case.find("skipped") is not None for case in cases)
        if counts["failures"] or counts["errors"]:
            raise ValueError("Pytest reported failing tests or errors.")
        if counts["tests"] != len(cases) or counts["skipped"] != skipped:
            raise ValueError("Malformed pytest report: cases disagree with suite totals.")
        if suite.find("testsuite") is not None:
            raise ValueError("Malformed pytest report: unexpected nested suites.")
        passed += len(cases) - skipped
    if passed < 1:
        raise ValueError("No tests actually passed; empty, all-skipped, or all-xfailed runs are not acceptance.")
    return passed


def run_tests(root: Path, profile: str, env: dict[str, str]) -> int:
    """Run the pinned native runner once and require at least one reported pass."""
    if profile not in {"typescript-web", "python-service"}:
        raise ValueError(f"Unsupported test profile: {profile}")
    root = root.resolve()
    cache = root / ".project/cache"
    if cache.is_symlink() or cache.parent.is_symlink():
        raise ValueError("Test-report cache must not be a symlink.")
    cache.mkdir(parents=True, exist_ok=True)
    # A new directory per invocation prevents a prior successful report being reused.
    with tempfile.TemporaryDirectory(prefix="test-report-", dir=cache) as directory:
        report = Path(directory) / ("results.json" if profile == "typescript-web" else "results.xml")
        if profile == "typescript-web":
            args = ["node", str(root / "node_modules/vitest/vitest.mjs"), "run", "--dir", "tests",
                    "--reporter=default", "--reporter=json", f"--outputFile.json={report}",
                    "--passWithNoTests=false",
                    "--allowOnly=false", "--testNamePattern=.*", "--update=none",
                    "--dangerouslyIgnoreUnhandledErrors=false"]
            parse = vitest_passes
        else:
            args = [str(root / ".venv/bin/python"), "-I", "-B",
                    str(root / ".project/python_environment.py"), "pytest", "tests",
                    "-p", "no:cacheprovider", "-o", "addopts=", "--strict-config", "--strict-markers",
                    "-o", "junit_family=xunit2", "-o", "strict_xfail=True", f"--junitxml={report}"]
            parse = pytest_passes
        print("+ " + " ".join(args), flush=True)
        subprocess.run(args, cwd=root, env=test_environment(env), check=True)
        passed = parse(report)
        print(f"Test acceptance: {passed} test(s) passed with a fresh native result report.")
        return passed
