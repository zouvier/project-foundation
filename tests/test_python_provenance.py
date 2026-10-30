"""R1/R2: actual Python installations/imports must belong to this repository."""
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from conftest import ROOT, git, tracked_bytes, tree_bytes
from test_acceptance import domain_file, edited


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "template/.project" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


environment = load_helper("command_environment")
provenance = load_helper("python_environment")


def test_environment_owns_project_interpreter_and_install_selection(tmp_path):
    controls = {name: "/wrong" for name in [
        "UV_PROJECT", "UV_WORKING_DIR", "UV_PROJECT_ENVIRONMENT", "UV_PYTHON", "UV_PYTHON_PREFERENCE",
        "UV_NO_EDITABLE", "UV_FROZEN", "UV_NO_DEV", "UV_NO_DEFAULT_GROUPS", "UV_NO_GROUP",
        "UV_NO_INSTALL_PROJECT", "UV_NO_INSTALL_LOCAL", "UV_NO_INSTALL_WORKSPACE",
        "UV_NO_INSTALLER_METADATA", "UV_NO_SYNC", "UV_CONFIG_FILE", "UV_ENV_FILE", "UV_TARGET",
        "UV_PREFIX", "UV_FUTURE_PROJECT_OVERRIDE", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
        "PYTHONOPTIMIZE", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "CONDA_PREFIX", "__PYVENV_LAUNCHER__",
    ]}
    preserved = {"PATH": "/bin", "PORT": "8001", "APP_MODE": "local", "UV_OFFLINE": "true",
                 "UV_LINK_MODE": "copy", "UV_HTTP_TIMEOUT": "60", "UV_CONCURRENT_INSTALLS": "1",
                 "UV_DEFAULT_INDEX": "https://pypi.org/simple", "UV_PYTHON_INSTALL_DIR": "/runtimes"}
    inherited = {**controls, **preserved}
    cleaned = environment.command_environment(tmp_path, inherited)
    assert all(cleaned[key] == value for key, value in preserved.items())
    assert not (set(controls) - {"UV_PROJECT_ENVIRONMENT"}) & cleaned.keys()
    assert cleaned["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / ".venv")
    assert cleaned["UV_CACHE_DIR"] == str(tmp_path / ".cache/uv")
    assert cleaned["UV_PYTHON_DOWNLOADS"] == "never"
    assert inherited == {**controls, **preserved}


@pytest.mark.parametrize("origin,locations", [
    ("/another/src/pkg/__init__.py", ["/another/src/pkg"]),
    (None, ["/another/src/pkg"]), (None, None), (None, []),
])
def test_external_or_unverifiable_module_origins_fail(tmp_path, origin, locations):
    with pytest.raises(ValueError, match="provenance"):
        provenance.module_origin("pkg", origin, locations, tmp_path / "src/pkg")


def test_loaded_submodule_cannot_hide_behind_local_root(tmp_path, monkeypatch):
    source = tmp_path / "src/unit_pkg"
    root_module = SimpleNamespace(__file__=str(source / "__init__.py"), __path__=[str(source)])
    wrong_module = SimpleNamespace(__file__=str(tmp_path / "elsewhere/greeting.py"))
    monkeypatch.setitem(provenance.sys.modules, "unit_pkg", root_module)
    monkeypatch.setitem(provenance.sys.modules, "unit_pkg.domain.greeting", wrong_module)
    with pytest.raises(ValueError, match="unit_pkg.domain.greeting.*outside"):
        provenance.loaded_sources("unit_pkg", source)


def test_collected_test_module_must_be_local(tmp_path):
    item = SimpleNamespace(path=tmp_path / "tests/test_local.py", nodeid="test_local.py::test_one",
                           module=SimpleNamespace(__file__="/another/test_local.py"), obj=None)
    with pytest.raises(ValueError, match="Collected test module"):
        provenance.collected_sources([item], tmp_path / "tests")


def assert_unchanged(project, before, state):
    assert tracked_bytes(project) == before, "Canonical command changed tracked inputs"
    assert (project / ".project/local-state.json").read_bytes() == state, "Read-only command rewrote readiness"


def origins(project, evidence, *, env=None):
    package = project.name.replace("-", "_")
    code = (f"import importlib.metadata as m, json, {package}.domain.greeting as g; "
            f"print(json.dumps({{'origin': g.__file__, 'direct': "
            f"json.loads(m.distribution({project.name!r}).read_text('direct_url.json'))}}))")
    result = evidence.run([project / ".venv/bin/python", "-B", "-c", code], cwd=project, env=env)
    return json.loads(result.stdout)


def raw_pytest(project, evidence, *, env=None):
    # Deliberate negative control: no canonical environment/provenance guard.
    return evidence.run([project / ".venv/bin/python", "-B", "-m", "pytest", "tests", "-q",
                         "-p", "no:cacheprovider", "-o", "addopts="], cwd=project, env=env)


def raw_uv_sync(project, evidence, source, *, noneditable=False):
    args = ["uv", "--project", source, "--directory", project, "sync", "--locked",
            "--no-build-isolation", "--python", "3.13.5"]
    if noneditable:
        args.append("--no-editable")
    evidence.run(args, cwd=project, timeout=300, env={
        "UV_PROJECT_ENVIRONMENT": str(project / ".venv"), "UV_CACHE_DIR": str(project / ".cache/uv"),
        "UV_PYTHON_DOWNLOADS": "never", "PYTHONDONTWRITEBYTECODE": "1", "UV_LINK_MODE": "copy",
    })


def test_r1_stale_wheel_is_rejected_then_explicit_bootstrap_repairs(projects, evidence):
    project = projects[("python-service", "beta")]
    source = domain_file(project, "python-service")
    original = source.read_text()
    try:
        raw_uv_sync(project, evidence, project, noneditable=True)
        installed = origins(project, evidence)
        assert "/site-packages/" in installed["origin"]
        assert installed["direct"].get("dir_info", {}).get("editable") is not True
        with edited(source, original.replace("Hello,", "Broken,")):
            assert source.read_text() != original
            before, state = tracked_bytes(project), (project / ".project/local-state.json").read_bytes()
            assert "8 passed" in raw_pytest(project, evidence).stdout, "Stale-source negative control did not reproduce"
            for action in ["doctor", "check", "test"]:
                result = evidence.run([project / "project", action], cwd=project, expected="failure")
                assert "editable installation" in result.stdout, result.stdout
                assert "bootstrap" in result.stdout
                assert_unchanged(project, before, state)
            evidence.run([project / "project", "bootstrap"], cwd=project, env={"UV_NO_EDITABLE": "true"}, timeout=300)
            installed = origins(project, evidence)
            assert installed["direct"]["dir_info"]["editable"] is True
            assert installed["origin"] == str(source)
            evidence.run([project / "project", "doctor"], cwd=project)
            for action in ["check", "test"]:
                result = evidence.run([project / "project", action], cwd=project, expected="failure",
                                      env={"UV_NO_EDITABLE": "true"})
                assert "AssertionError" in result.stdout and "Broken," in result.stdout, result.stdout
                assert tracked_bytes(project) == before
    finally:
        evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
    evidence.run([project / "project", "check"], cwd=project)
    assert git(project, "status", "--porcelain") == ""


def test_r1_inherited_pythonpath_cannot_mask_changed_workspace(projects, evidence, tmp_path):
    project = projects[("python-service", "beta")]
    source = domain_file(project, "python-service")
    original = source.read_text()
    external = tmp_path / "shadow-source"
    shutil.copytree(project / "src", external)
    with edited(source, original.replace("Hello,", "Broken,")):
        assert source.read_text() != original
        before, state = tracked_bytes(project), (project / ".project/local-state.json").read_bytes()
        env = {"PYTHONPATH": str(external)}
        assert origins(project, evidence, env=env)["origin"].startswith(str(external))
        assert "8 passed" in raw_pytest(project, evidence, env=env).stdout, "External-source negative control did not reproduce"
        # These startup overrides must not break the driver before normalization.
        env.update({"PYTHONHOME": str(tmp_path / "missing-python"), "PYTHONOPTIMIZE": "2",
                    "PYTHONUSERBASE": str(tmp_path / "user-site")})
        evidence.run([project / "project", "doctor"], cwd=tmp_path, env=env)
        for action in ["check", "test"]:
            result = evidence.run([project / "project", action], cwd=tmp_path, env=env, expected="failure")
            assert "AssertionError" in result.stdout and "Broken," in result.stdout, result.stdout
            assert "Python provenance: editable workspace src" in result.stdout
            assert_unchanged(project, before, state)
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("control", ["UV_PROJECT", "UV_WORKING_DIR", "combined"])
def test_r2_bootstrap_ignores_external_project_and_install_controls(projects, evidence, tmp_path, control):
    project, sibling = projects[("python-service", "beta")], projects[("python-service", "alpha")]
    before, other = tracked_bytes(project), tree_bytes(sibling)
    other_state = (sibling / ".project/local-state.json").read_bytes()
    env = {control: str(sibling)}
    if control == "combined":
        env = {
            "UV_PROJECT": str(sibling), "UV_WORKING_DIR": str(sibling),
            "UV_PROJECT_ENVIRONMENT": str(tmp_path / "wrong-venv"), "VIRTUAL_ENV": str(sibling / ".venv"),
            "CONDA_PREFIX": str(sibling / ".venv"), "UV_PYTHON": str(tmp_path / "missing-python"),
            "UV_CONFIG_FILE": str(tmp_path / "missing-config.toml"), "UV_ENV_FILE": str(tmp_path / "missing.env"),
            "UV_NO_EDITABLE": "true", "UV_NO_DEV": "true", "UV_NO_DEFAULT_GROUPS": "true",
            "UV_NO_INSTALL_PROJECT": "true", "UV_NO_INSTALL_LOCAL": "true", "UV_NO_INSTALLER_METADATA": "true",
            "UV_FROZEN": "true", "UV_NO_SYNC": "true", "PYTHONPATH": str(sibling / "src"),
        }
    evidence.run([project / "project", "bootstrap"], cwd=tmp_path, env=env, timeout=300)
    installed = origins(project, evidence)
    assert installed["direct"]["dir_info"]["editable"] is True
    assert installed["origin"] == str(domain_file(project, "python-service"))
    for action in ["doctor", "check", "test"]:
        evidence.run([project / "project", action], cwd=tmp_path, env=env)
    assert not (tmp_path / "wrong-venv").exists()
    assert tree_bytes(sibling) == other
    assert (sibling / ".project/local-state.json").read_bytes() == other_state
    assert tracked_bytes(project) == before
    assert git(project, "status", "--porcelain") == ""


def test_r2_already_redirected_environment_needs_explicit_bootstrap(projects, evidence):
    project, sibling = projects[("python-service", "beta")], projects[("python-service", "alpha")]
    before, other = tracked_bytes(project), tree_bytes(sibling)
    state = (project / ".project/local-state.json").read_bytes()
    try:
        raw_uv_sync(project, evidence, sibling)
        for action in ["doctor", "check", "test"]:
            result = evidence.run([project / "project", action], cwd=project, expected="failure")
            assert "Expected one installed service-beta distribution" in result.stdout, result.stdout
            assert "bootstrap" in result.stdout
            assert_unchanged(project, before, state)
    finally:
        evidence.run([project / "project", "bootstrap"], cwd=project, env={"UV_PROJECT": str(sibling)}, timeout=300)
    evidence.run([project / "project", "check"], cwd=project)
    assert tree_bytes(sibling) == other
    assert git(project, "status", "--porcelain") == ""


def test_r1_pytest_local_pythonpath_config_cannot_shadow_workspace(projects, evidence, tmp_path):
    project = projects[("python-service", "beta")]
    external = tmp_path / "shadow-source"
    shutil.copytree(project / "src", external)
    # A normal pytest config option can change sys.path after the initial doctor
    # probe. The in-process guard must check again after pytest configuration.
    ini = "[pytest]\npythonpath = " + str(external) + "\n"
    with edited(project / "pytest.ini", ini):
        before = tracked_bytes(project)
        result = evidence.run([project / "project", "test"], cwd=project, expected="failure")
        assert "provenance" in result.stdout and "outside" in result.stdout, result.stdout
        assert tracked_bytes(project) == before


def test_r1_stale_submodule_is_rejected_after_collection(projects, evidence, tmp_path):
    project = projects[("python-service", "beta")]
    external = tmp_path / "greeting.py"
    external.write_bytes(domain_file(project, "python-service").read_bytes())
    content = ("import importlib.util\nimport sys\n"
               "import service_beta.domain\n"
               f"spec = importlib.util.spec_from_file_location('service_beta.domain.greeting', {str(external)!r})\n"
               "module = importlib.util.module_from_spec(spec)\n"
               "spec.loader.exec_module(module)\n"
               "sys.modules['service_beta.domain.greeting'] = module\n")
    with edited(project / "tests/test_aaa_provenance.py", content):
        before = tracked_bytes(project)
        assert "8 passed" in raw_pytest(project, evidence).stdout
        result = evidence.run([project / "project", "test"], cwd=project, expected="failure")
        assert "service_beta.domain.greeting" in result.stdout and "outside" in result.stdout, result.stdout
        assert tracked_bytes(project) == before


def test_r1_submodule_redirect_during_test_execution_is_rejected(projects, evidence, tmp_path):
    project = projects[("python-service", "beta")]
    external = tmp_path / "greeting.py"
    external.write_bytes(domain_file(project, "python-service").read_bytes())
    content = ("import importlib.util\nimport sys\n\ndef test_runtime_redirect():\n"
               f"    spec = importlib.util.spec_from_file_location('service_beta.domain.greeting', {str(external)!r})\n"
               "    module = importlib.util.module_from_spec(spec)\n"
               "    spec.loader.exec_module(module)\n"
               "    sys.modules['service_beta.domain.greeting'] = module\n")
    with edited(project / "tests/test_zzz_runtime.py", content):
        before = tracked_bytes(project)
        assert "9 passed" in raw_pytest(project, evidence).stdout
        result = evidence.run([project / "project", "test"], cwd=project, expected="failure")
        assert "service_beta.domain.greeting" in result.stdout and "outside" in result.stdout, result.stdout
        assert "teardown" in result.stdout.lower(), result.stdout
        assert tracked_bytes(project) == before


def test_r1_collected_callable_from_external_file_is_rejected(projects, evidence, tmp_path):
    project = projects[("python-service", "beta")]
    external = tmp_path / "external_test.py"
    external.write_text("def test_external():\n    assert True\n")
    content = f"import runpy\ntest_external = runpy.run_path({str(external)!r})['test_external']\n"
    with edited(project / "tests/test_external.py", content):
        before = tracked_bytes(project)
        assert "9 passed" in raw_pytest(project, evidence).stdout
        result = evidence.run([project / "project", "test"], cwd=project, expected="failure")
        assert "Collected test callable" in result.stdout, result.stdout
        assert tracked_bytes(project) == before
