"""F2 report and runner-contract regressions, without installed project dependencies."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "template/.project/test_runner.py"
SPEC = importlib.util.spec_from_file_location("foundation_test_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def web_report(statuses=("passed",)):
    return {
        "success": True,
        "numTotalTests": len(statuses),
        "numPassedTests": statuses.count("passed"),
        "numFailedTests": statuses.count("failed"),
        "numFailedTestSuites": 0,
        "testResults": [{"status": "passed", "assertionResults": [
            {"status": status, "failureMessages": []} for status in statuses
        ]}],
    }


def write_json(tmp_path, value):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(value))
    return path


def python_report(cases, *, tests=None, skipped=0, failures=0, errors=0):
    tests = len(cases) if tests is None else tests
    return (f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" '
            f'failures="{failures}" errors="{errors}">' + "".join(cases) + "</testsuite></testsuites>")


PASS = '<testcase name="ordinary" time="0.01"/>'
SKIP = '<testcase name="skip"><skipped/></testcase>'
XFAIL = '<testcase name="xfail"><skipped type="pytest.xfail"/></testcase>'


def write_xml(tmp_path, value):
    path = tmp_path / "results.xml"
    path.write_text(value)
    return path


def test_web_counts_assertions_not_only_summary(tmp_path):
    assert runner.vitest_passes(write_json(tmp_path, web_report(("passed", "skipped", "todo")))) == 1


def test_web_all_skipped_file_beside_passing_file_is_valid(tmp_path):
    # Native Vitest 5 marks each file passed, even a file whose assertions all skip.
    report = web_report(("passed", "skipped"))
    passed, skipped = report["testResults"][0]["assertionResults"]
    report["testResults"] = [
        {"status": "passed", "assertionResults": [passed]},
        {"status": "passed", "assertionResults": [skipped]},
    ]
    report["numPendingTests"] = 1  # Vitest includes ordinary skipped tests here.
    assert runner.vitest_passes(write_json(tmp_path, report)) == 1


def test_web_all_skipped_is_reported_as_no_execution_not_malformed(tmp_path):
    report = web_report(("skipped",))
    report["numPendingTests"] = 1
    with pytest.raises(ValueError, match="No tests actually passed.*all-skipped"):
        runner.vitest_passes(write_json(tmp_path, report))


@pytest.mark.parametrize("statuses", [(), ("skipped",), ("todo",), ("failed",), ("pending",), ("unknown",)])
def test_web_empty_skipped_failed_or_incomplete_run_fails(tmp_path, statuses):
    with pytest.raises(ValueError):
        runner.vitest_passes(write_json(tmp_path, web_report(statuses)))


@pytest.mark.parametrize("key,value", [
    ("success", False), ("success", 1), ("numTotalTests", 99), ("numPassedTests", 0),
    ("numPassedTests", True), ("numFailedTests", 1), ("numFailedTestSuites", 1),
    ("testResults", {}),
])
def test_web_malformed_or_failed_summary_fails(tmp_path, key, value):
    report = web_report()
    report[key] = value
    with pytest.raises(ValueError):
        runner.vitest_passes(write_json(tmp_path, report))


def test_web_cannot_hide_assertion_failure_in_passing_summary(tmp_path):
    report = web_report()
    report["testResults"][0]["assertionResults"][0]["failureMessages"] = ["failed assertion"]
    with pytest.raises(ValueError):
        runner.vitest_passes(write_json(tmp_path, report))


def test_python_counts_passes_excluding_skip_and_xfail(tmp_path):
    report = python_report([PASS, SKIP, XFAIL], skipped=2)
    assert runner.pytest_passes(write_xml(tmp_path, report)) == 1


@pytest.mark.parametrize("cases,skipped", [([], 0), ([SKIP], 1), ([XFAIL], 1), ([SKIP, XFAIL], 2)])
def test_python_empty_skipped_or_xfailed_run_fails(tmp_path, cases, skipped):
    with pytest.raises(ValueError):
        runner.pytest_passes(write_xml(tmp_path, python_report(cases, skipped=skipped)))


@pytest.mark.parametrize("report", [
    '<testsuites/>', '<anything/>',
    '<testsuites><testsuite><testcase/></testsuite></testsuites>',
    python_report([PASS], tests=0), python_report([PASS], skipped=1),
    python_report([PASS], failures=1), python_report([PASS], errors=1),
    python_report(['<testcase><failure/></testcase>']),
    python_report(['<testcase><error/></testcase>']),
])
def test_python_malformed_or_failure_report_fails(tmp_path, report):
    with pytest.raises(ValueError):
        runner.pytest_passes(write_xml(tmp_path, report))


@pytest.mark.parametrize("parse", [runner.vitest_passes, runner.pytest_passes])
def test_missing_malformed_or_symlink_report_fails(tmp_path, parse):
    path = tmp_path / "missing"
    with pytest.raises(ValueError):
        parse(path)
    path.write_text("not a valid report")
    with pytest.raises(ValueError):
        parse(path)
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="fresh regular"):
        parse(alias)


def test_environment_removes_inherited_runner_shortcuts_without_mutating_input():
    original = {"PATH": "/bin", "HOME": "/safe/home", "PYTEST_ADDOPTS": "--collect-only",
                "PYTEST_PLUGINS": "injected", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "VITEST_SEGFAULT_RETRY": "9", "NODE_OPTIONS": "--require injected",
                "NODE_ENV": "production", "PYTHONOPTIMIZE": "2", "CI": "false",
                "PYTHONPATH": "/another/src", "PYTHONHOME": "/another/python",
                "__PYVENV_LAUNCHER__": "/another/python"}
    cleaned = runner.test_environment(original)
    assert cleaned == {"PATH": "/bin", "HOME": "/safe/home", "CI": "true",
                       "NODE_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"}
    assert original["PYTEST_ADDOPTS"] == "--collect-only"


@pytest.mark.parametrize("profile", ["typescript-web", "python-service"])
def test_native_command_environment_fresh_reports_and_cleanup(tmp_path, monkeypatch, profile):
    reports = []
    invocations = []

    def native(args, **kwargs):
        assert kwargs["check"] is True
        assert kwargs["cwd"] == tmp_path
        assert kwargs["env"]["CI"] == "true"
        assert not any(key.startswith(("PYTEST_", "VITEST_")) for key in kwargs["env"])
        flag = "--outputFile.json=" if profile == "typescript-web" else "--junitxml="
        report = Path(next(value[len(flag):] for value in args if value.startswith(flag)))
        assert not report.exists()
        reports.append(report)
        invocations.append(args)
        if profile == "typescript-web":
            report.write_text(json.dumps(web_report()))
        else:
            report.write_text(python_report([PASS]))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner.subprocess, "run", native)
    for _ in range(2):
        assert runner.run_tests(tmp_path, profile, {"PYTEST_ADDOPTS": "--collect-only"}) == 1
    assert reports[0] != reports[1]
    assert all(not path.parent.exists() for path in reports)
    assert list((tmp_path / ".project/cache").iterdir()) == []
    args = invocations[0]
    if profile == "typescript-web":
        assert args[:5] == ["node", str(tmp_path / "node_modules/vitest/vitest.mjs"), "run", "--dir", "tests"]
        assert {"--passWithNoTests=false", "--allowOnly=false", "--testNamePattern=.*"}.issubset(args)
        assert {"--reporter=default", "--reporter=json"}.issubset(args)
    else:
        assert args[:6] == [str(tmp_path / ".venv/bin/python"), "-I", "-B",
                            str(tmp_path / ".project/python_environment.py"), "pytest", "tests"]
        assert "addopts=" in args and "no:cacheprovider" in args


@pytest.mark.parametrize("outcome", ["nonzero", "missing", "malformed"])
def test_run_cannot_pass_without_current_successful_native_report(tmp_path, monkeypatch, outcome):
    def native(args, **kwargs):
        if outcome == "nonzero":
            raise subprocess.CalledProcessError(3, args)
        if outcome == "malformed":
            flag = "--outputFile.json="
            path = Path(next(value[len(flag):] for value in args if value.startswith(flag)))
            path.write_text("{}")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner.subprocess, "run", native)
    with pytest.raises(subprocess.CalledProcessError if outcome == "nonzero" else ValueError):
        runner.run_tests(tmp_path, "typescript-web", {})
    assert list((tmp_path / ".project/cache").iterdir()) == []


def test_invalid_profile_fails_before_creating_cache(tmp_path):
    with pytest.raises(ValueError, match="Unsupported test profile"):
        runner.run_tests(tmp_path, "invalid", {})
    assert list(tmp_path.iterdir()) == []


def test_symlinked_cache_is_rejected(tmp_path):
    (tmp_path / ".project").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".project/cache").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        runner.run_tests(tmp_path, "typescript-web", {})
