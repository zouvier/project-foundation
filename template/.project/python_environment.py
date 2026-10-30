"""Verify the editable workspace and native pytest source provenance.

These are consistency checks on installed metadata and actual import origins,
not a sandbox or protection from intentionally forged Python modules/reports.
Doctor inspects the root spec without executing application __init__.py.
"""
import importlib.metadata
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


def fail(message):
    raise ValueError("Python environment provenance: " + message)


def within(value, directory):
    if not isinstance(value, (str, Path)) or not str(value):
        return False
    return Path(value).resolve().is_relative_to(directory.resolve())


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def module_origin(name, origin, locations, source):
    if origin is not None and not within(origin, source):
        fail(f"{name} resolves outside this repository's src package: {origin}. "
             "Run ./project bootstrap and remove conflicting local import-path configuration.")
    if locations is not None:
        locations = list(locations)
        if not locations or any(not within(path, source) for path in locations):
            fail(f"{name} has package search locations outside this repository's src package. "
                 "Run ./project bootstrap and remove conflicting local import-path configuration.")
    elif origin is None:
        fail(f"{name} has no verifiable source origin.")


def verify(root):
    """Require this .venv, one editable root distribution, and local root spec."""
    root = root.resolve()
    meta = json.loads((root / ".project/project.json").read_text())
    name, package = meta["name"], meta["package_name"]
    source = root / "src" / package
    if Path(sys.prefix).resolve() != root / ".venv":
        fail("The interpreter is not this repository's .venv. Run ./project bootstrap.")
    matches = [dist for dist in importlib.metadata.distributions()
               if normalized(dist.metadata.get("Name", "")) == normalized(name)]
    if len(matches) != 1 or not within(matches[0].locate_file(""), root / ".venv"):
        fail(f"Expected one installed {name} distribution in this .venv. Run ./project bootstrap.")
    try:
        direct = json.loads(matches[0].read_text("direct_url.json") or "null")
        url = urlsplit(direct["url"])
        editable = direct["dir_info"]["editable"] is True
        local = (url.scheme == "file" and url.netloc in {"", "localhost"}
                 and not url.query and not url.fragment and Path(unquote(url.path)).resolve() == root)
    except (KeyError, TypeError, ValueError):
        editable = local = False
    if not editable or not local:
        fail(f"{name} must be an editable installation of this repository, not a wheel or sibling copy. "
             "Run ./project bootstrap explicitly; check/test never repair installations.")
    spec = importlib.util.find_spec(package)
    if spec is None or spec.submodule_search_locations is None:
        fail(f"Cannot resolve the {package} src package. Run ./project bootstrap.")
    module_origin(package, spec.origin, spec.submodule_search_locations, source)
    if [Path(path).resolve() for path in spec.submodule_search_locations] != [source]:
        fail(f"{package} must resolve directly to {source}. Run ./project bootstrap.")
    return package, source


def loaded_sources(package, source):
    """Check root/submodules actually imported by collection or test execution."""
    for name, module in list(sys.modules.items()):
        if module is None or not (name == package or name.startswith(package + ".")):
            continue
        spec = getattr(module, "__spec__", None)
        module_origin(name, getattr(module, "__file__", None), getattr(module, "__path__", None), source)
        if spec is not None:
            module_origin(name, spec.origin, spec.submodule_search_locations, source)


def collected_sources(items, tests):
    for item in items:
        if not within(item.path, tests):
            fail(f"Collected test path is outside this repository's tests/: {item.path}.")
        module = getattr(item, "module", None)
        if module is not None and not within(getattr(module, "__file__", None), tests):
            fail(f"Collected test module is outside this repository's tests/: {item.nodeid}.")
        obj = getattr(item, "obj", None)
        if obj is not None:
            try:
                origin = inspect.getsourcefile(inspect.unwrap(obj))
            except TypeError:
                origin = None
            if not within(origin, tests):
                fail(f"Collected test callable has no source inside this repository's tests/: {item.nodeid}.")


def run_pytest(root, args):
    import pytest

    package, source = verify(root)

    class SourceGuard:
        def inspect_imports(self):
            verify(root)
            loaded_sources(package, source)

        def pytest_sessionstart(self, session):
            try:
                self.inspect_imports()
            except ValueError as error:
                raise pytest.UsageError(str(error)) from error

        def pytest_collection_finish(self, session):
            try:
                self.inspect_imports()
                collected_sources(session.items, root / "tests")
            except ValueError as error:
                raise pytest.UsageError(str(error)) from error
            print(f"Python provenance: editable workspace src; {len(session.items)} local test item(s).", flush=True)

        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_setup(self, item):
            self.inspect_imports()

        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_teardown(self, item, nextitem):
            # Inspect before fixture teardown can remove an imported module.
            self.inspect_imports()

        def pytest_sessionfinish(self, session, exitstatus):
            try:
                self.inspect_imports()
            except ValueError as error:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
                reporter = session.config.pluginmanager.get_plugin("terminalreporter")
                if reporter is not None:
                    reporter.write_line(str(error), red=True)

    return int(pytest.main(args, plugins=[SourceGuard()]))


def main():
    root = Path(__file__).resolve().parents[1]
    # A normal timestamp pyc can be stale after a same-size edit in one second.
    # Read from a fresh, nonexistent prefix and write nothing; doctor stays read-only.
    sys.dont_write_bytecode = True
    sys.pycache_prefix = str(root / ".project/cache" / ("source-" + os.urandom(16).hex()))
    if sys.argv[1:] == ["verify"]:
        verify(root)
        return 0
    if len(sys.argv) > 2 and sys.argv[1] == "pytest":
        return run_pytest(root, sys.argv[2:])
    fail("Expected verify or pytest arguments.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as error:
        print(f"project: {error}", file=sys.stderr)
        sys.exit(1)
