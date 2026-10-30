"""Offline regressions for dependency names, identity drift, and Copier provenance."""
import ast
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

import pytest

from conftest import COPIER, ROOT, generate, git, tree_bytes

MODULE_PATH = ROOT / "template/.project/identity.py"
SPEC = importlib.util.spec_from_file_location("foundation_identity", MODULE_PATH)
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)
PROFILES = ["typescript-web", "python-service"]


def locked_names():
    python_lock = next((ROOT / "template").glob("*uv.lock*"))
    python = tomllib.loads(python_lock.read_text().replace("{{ project_name }}", "root-placeholder"))
    python_names = {re.sub(r"[-_.]+", "-", p["name"]).lower()
                    for p in python["package"] if p["name"] != "root-placeholder"}
    web_lock = next((ROOT / "template").glob("*package-lock*"))
    web = json.loads(web_lock.read_text().replace("{{ project_name }}", "root-placeholder"))
    web_names = {key.rsplit("node_modules/", 1)[-1] for key in web["packages"] if key}
    return python_names, web_names


PYTHON_NAMES, WEB_NAMES = locked_names()
ALIASES = {"attr", "opentelemetry", "rpds"}
GENERATABLE_RESERVED = sorted(name for name in PYTHON_NAMES | WEB_NAMES | ALIASES
                             if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name))


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture(scope="module")
def identity_projects(tmp_path_factory, template_repo, evidence):
    parent = tmp_path_factory.mktemp("identity-baselines")
    return {profile: generate(evidence, template_repo, parent / name, name, profile)
            for profile, name in [("typescript-web", "identity-web"),
                                  ("python-service", "identity-service")]}


@pytest.fixture
def project_copy(tmp_path, identity_projects):
    def copy(profile):
        destination = tmp_path / profile
        shutil.copytree(identity_projects[profile], destination)
        return destination
    return copy


def inspect(project):
    return identity.inspect_identity(project, read_json(project / ".project/project.json"))


def test_reserved_distribution_list_covers_actual_template_lock_graphs():
    config = (ROOT / "copier.yml").read_text()
    match = re.search(r"set reserved_distribution_names = (\[.*?\]) %}", config)
    assert match, "Keep the reserved distribution set explicit and testable in Copier's validator"
    declared = set(ast.literal_eval(match.group(1)))
    assert PYTHON_NAMES | WEB_NAMES | ALIASES <= declared
    assert {"pydantic", "starlette", "anyio", "pydantic-core", "typing-extensions"} <= declared


@pytest.mark.parametrize("name", GENERATABLE_RESERVED)
def test_copier_rejects_every_generatable_locked_dependency_name(
        tmp_path, template_repo, evidence, name):
    profile = "python-service" if name in PYTHON_NAMES | ALIASES else "typescript-web"
    result = evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", f"project_name={name}",
         "--data", f"profile={profile}", template_repo, tmp_path / "invalid"],
        cwd=tmp_path, expected="failure",
    )
    assert "reserved" in result.stdout.lower(), result.stdout


@pytest.mark.parametrize("profile", PROFILES)
def test_real_copier_receipt_matches_exact_source_and_is_read_only(identity_projects, template_repo, profile):
    project = identity_projects[profile]
    before = tree_bytes(project)
    receipt = read_json(project / ".project/template.json")
    answers = read_json(project / ".copier-answers.yml")
    assert receipt["source_path"] == answers["_src_path"] == str(template_repo)
    assert receipt["source_ref"] == answers["_commit"] == "v0.1.0"
    assert receipt["source_commit"] == git(template_repo, "rev-parse", "v0.1.0")
    assert receipt["foundation_version"] == "0.1.2"
    assert inspect(project) == receipt["runtime"]
    assert tree_bytes(project) == before


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("field,value", [
    ("name", "other-project"), ("package_name", "other_project"),
    ("foundation_version", "99.0.0"), ("profile", "unrecognized-profile"),
])
def test_metadata_identity_drift_is_rejected(project_copy, profile, field, value):
    project = project_copy(profile)
    path = project / ".project/project.json"
    meta = read_json(path)
    meta[field] = value
    write_json(path, meta)
    with pytest.raises(ValueError, match=field):
        inspect(project)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("field", ["_src_path", "_commit", "project_name", "profile", "package_name"])
def test_lineage_fields_cannot_disagree_with_receipt(project_copy, profile, field):
    project = project_copy(profile)
    path = project / ".copier-answers.yml"
    answers = read_json(path)
    answers[field] = "wrong-value"
    write_json(path, answers)
    with pytest.raises(ValueError, match=field):
        inspect(project)


@pytest.mark.parametrize("content", ["{}", "[]", "{", '{"_commit":"a", "_commit":"b"}', "_commit: v0.1.0\n"])
def test_missing_malformed_or_ambiguous_lineage_fails(project_copy, content):
    project = project_copy("typescript-web")
    (project / ".copier-answers.yml").write_text(content)
    with pytest.raises(ValueError, match="JSON|object|lineage|Duplicate"):
        inspect(project)


@pytest.mark.parametrize("field,value", [
    ("receipt_version", True), ("foundation_version", "unknown"),
    ("source_commit", None), ("source_commit", "unknown"), ("source_commit", "0" * 40),
    ("source_ref", None), ("source_ref", ""), ("project_name", "Bad Name"),
    ("profile", []), ("package_name", "wrong_package"), ("runtime", []),
])
def test_invalid_receipt_structure_fails_actionably(project_copy, field, value):
    project = project_copy("typescript-web")
    path = project / ".project/template.json"
    receipt = read_json(path)
    receipt[field] = value
    write_json(path, receipt)
    with pytest.raises(ValueError, match="Project identity:"):
        inspect(project)


@pytest.mark.parametrize("value", [".", "../template", "~/template", "https://", "https://example.org:bad/repo"])
def test_relative_or_invalid_source_paths_are_rejected(project_copy, value):
    project = project_copy("typescript-web")
    path = project / ".project/template.json"
    receipt = read_json(path)
    receipt["source_path"] = value
    write_json(path, receipt)
    with pytest.raises(ValueError, match="source_path must be absolute"):
        inspect(project)


@pytest.mark.parametrize("source", [
    "/unavailable/template-checkout", "https://example.org/org/template.git",
    "git+https://example.org/org/template.git", "ssh://git@example.org/org/template.git",
    "git@example.org:org/template.git",
])
def test_normal_validation_needs_no_template_checkout_or_network(project_copy, source):
    project = project_copy("typescript-web")
    for name, key in [(".project/template.json", "source_path"), (".copier-answers.yml", "_src_path")]:
        path = project / name
        value = read_json(path)
        value[key] = source
        write_json(path, value)
    assert inspect(project)["node"] == "24.11.1"


@pytest.mark.parametrize("profile", PROFILES)
def test_manifest_name_must_match_project_identity(project_copy, profile):
    project = project_copy(profile)
    if profile == "typescript-web":
        path = project / "package.json"
        value = read_json(path)
        value["name"] = "other-project"
        write_json(path, value)
    else:
        path = project / "pyproject.toml"
        path.write_text(path.read_text().replace('name = "identity-service"', 'name = "other-project"', 1))
    with pytest.raises(ValueError, match="metadata"):
        inspect(project)


@pytest.mark.parametrize("target", ["top", "packages"])
def test_both_npm_lock_root_names_are_validated(project_copy, target):
    project = project_copy("typescript-web")
    path = project / "package-lock.json"
    lock = read_json(path)
    if target == "top":
        lock["name"] = "other-project"
    else:
        lock["packages"][""]["name"] = "other-project"
    write_json(path, lock)
    with pytest.raises(ValueError, match="root names"):
        inspect(project)


def test_python_lock_root_name_is_validated(project_copy):
    project = project_copy("python-service")
    path = project / "uv.lock"
    path.write_text(path.read_text().replace('name = "identity-service"', 'name = "other-project"', 1))
    with pytest.raises(ValueError, match="editable root package"):
        inspect(project)


def test_python_normalized_root_distribution_collision_fails(project_copy):
    project = project_copy("python-service")
    path = project / "uv.lock"
    path.write_text(path.read_text() + '\n[[package]]\nname = "identity_service"\nversion = "1.0.0"\nsource = { registry = "https://pypi.org/simple" }\n')
    with pytest.raises(ValueError, match="collides"):
        inspect(project)


@pytest.mark.parametrize("profile,file", [("typescript-web", ".node-version"), ("python-service", ".python-version")])
def test_runtime_version_files_cannot_disagree_with_receipt(project_copy, profile, file):
    project = project_copy(profile)
    (project / file).write_text("99.0.0\n")
    with pytest.raises(ValueError, match="runtime pin"):
        inspect(project)


def test_npm_package_manager_pin_is_consistent(project_copy):
    project = project_copy("typescript-web")
    path = project / "package.json"
    value = read_json(path)
    value["packageManager"] = "npm@10.0.0"
    write_json(path, value)
    with pytest.raises(ValueError, match="packageManager"):
        inspect(project)


@pytest.mark.parametrize("profile", PROFILES)
def test_application_version_evolves_independently_of_foundation(project_copy, profile):
    project = project_copy(profile)
    if profile == "typescript-web":
        for name in ["package.json", "package-lock.json"]:
            path = project / name
            value = read_json(path)
            value["version"] = "7.8.9-preview.1+project.4"
            if "packages" in value:
                value["packages"][""]["version"] = value["version"]
            write_json(path, value)
    else:
        path = project / "pyproject.toml"
        path.write_text(path.read_text().replace('version = "0.1.0"', 'version = "7.8.9"', 1))
        path = project / "uv.lock"
        path.write_text(path.read_text().replace('name = "identity-service"\nversion = "0.1.0"',
                                                'name = "identity-service"\nversion = "7.8.9"', 1))
    assert inspect(project)
    assert read_json(project / ".project/template.json")["foundation_version"] == "0.1.2"


@pytest.mark.parametrize("profile", PROFILES)
def test_identity_does_not_freeze_dependency_graph(project_copy, profile):
    project = project_copy(profile)
    if profile == "typescript-web":
        path = project / "package-lock.json"
        value = read_json(path)
        value["packages"]["node_modules/future-library"] = {"version": "1.0.0"}
        write_json(path, value)
    else:
        path = project / "uv.lock"
        path.write_text(path.read_text() + '\n[[package]]\nname = "future-library"\nversion = "1.0.0"\nsource = { registry = "https://pypi.org/simple" }\n')
    # Full dependency consistency is the lock/bootstrap check's responsibility.
    assert inspect(project)


@pytest.mark.parametrize("replacement", [
    '"name" = "identity-service"', 'name = """identity-service"""',
    'name = "identity-service"\nname = "other-name"',
    'name = "identity-service"\n[project]\nname = "other-name"',
])
def test_unsupported_or_duplicate_toml_identity_syntax_fails_clearly(project_copy, replacement):
    project = project_copy("python-service")
    path = project / "pyproject.toml"
    path.write_text(path.read_text().replace('name = "identity-service"', replacement, 1))
    with pytest.raises(ValueError, match="Unsupported|Duplicate"):
        inspect(project)


def test_toml_identity_supports_single_quotes_comments_and_header_spacing(project_copy):
    project = project_copy("python-service")
    path = project / "pyproject.toml"
    path.write_text(path.read_text().replace("[project]", "[ project ] # identity").replace(
        'name = "identity-service"', "name = 'identity-service' # project name", 1))
    assert inspect(project)["python"] == "3.13.5"


def test_real_copier_relative_source_fails_before_bootstrap(tmp_path, template_repo, evidence):
    project = tmp_path / "relative-source"
    evidence.run([COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", "project_name=relative-source",
                  "--data", "profile=typescript-web", ".", project], cwd=template_repo)
    assert read_json(project / ".copier-answers.yml")["_src_path"] == "."
    with pytest.raises(ValueError, match="regenerate using an absolute source"):
        inspect(project)


def test_non_git_template_has_no_fabricated_provenance(tmp_path, template_repo, evidence):
    source = tmp_path / "unversioned-source"
    source.mkdir()
    shutil.copy2(template_repo / "copier.yml", source / "copier.yml")
    shutil.copytree(template_repo / "template", source / "template")
    project = tmp_path / "unversioned-project"
    evidence.run([COPIER, "copy", "--defaults", "--data", "project_name=unversioned-project",
                  "--data", "profile=typescript-web", source, project], cwd=tmp_path)
    with pytest.raises(ValueError, match="source ref/hash"):
        inspect(project)


def test_identity_reader_is_python39_syntax_and_uses_only_stdlib(identity_projects):
    ast.parse(MODULE_PATH.read_text(), feature_version=(3, 9))
    project = identity_projects["python-service"]
    runner = shutil.which("python3")
    assert runner
    result = subprocess.run([runner, "-B", "-c",
        "import json,sys; from pathlib import Path; sys.path.insert(0,'.project'); "
        "from identity import inspect_identity; "
        "print(json.dumps(inspect_identity(Path('.'),json.loads(Path('.project/project.json').read_text()))))"],
        cwd=project, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["python"] == "3.13.5"
