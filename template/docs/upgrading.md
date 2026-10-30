# Upgrade the foundation contract

Use the **Copier 9.19.1** executable from the foundation's separate local environment. Generated projects do not need Copier for normal development. Upgrade only from a reviewed template release; keep the same profile. Changing profiles is a separate migration.

## Ownership

| Paths | Update behavior |
| --- | --- |
| `src/**`, `tests/**`, `README.md`, `docs/architecture.md`, `docs/decisions/**`, `.project/tasks/**` | Project-owned seeds. Excluded when Copier updates; edited and deleted files stay under project control. |
| `project`, `.project/*.py`, `.project/validate.*`, `.project/schemas/**`, `.project/roles/**`, `.project/project.json`, `.project/template.json`, `AGENTS.md`, `docs/upgrading.md` | Template-managed contract and provenance/runtime receipt. Updates are reviewed diffs; local edits can conflict. |
| Stack manifests/locks/configuration, web `index.html`, `.gitignore`, `.vscode/tasks.json`, CI configuration | Template-managed baseline with project customization. Review dependency and configuration changes explicitly and resolve conflicts. |
| `.copier-answers.yml` | Copier-owned lineage. Commit it; never edit it manually. |
| `.venv/`, `node_modules/`, caches, `dist/`, `.project/local-state.json`, local secrets | Local state. Ignored and not distributed by the template. |

For a newly added domain path outside the seed-only list, decide ownership before accepting an upgrade that touches it. Exclusions preserve existing domain files; they do not update your architecture or tests to match changed tooling automatically.

## Review an explicit release

First finish or commit existing work. `git status --porcelain` must be empty. Run `./project check` and `./project build` on the current baseline, and preserve their results. Then create a dedicated branch:

```sh
git switch -c chore/foundation-upgrade
```

Point `FOUNDATION_COPIER` to the existing foundation environment's absolute Copier path. Set `TARGET_REF` to the exact release tag you have reviewed. For example, use `v0.1.2` only if that is the intended release; it will not discover a newer version automatically.

```sh
FOUNDATION_COPIER=/absolute/path/to/project-foundation/.venv/bin/copier
TARGET_REF=v0.1.2
"$FOUNDATION_COPIER" --version
"$FOUNDATION_COPIER" update --defaults --vcs-ref "$TARGET_REF" --pretend
"$FOUNDATION_COPIER" update --defaults --vcs-ref "$TARGET_REF"
git status --short
git diff
```

The dry run is optional and is not proof that an update will be conflict-free. Copier uses the recorded template source from `.copier-answers.yml`; that source and its release history must remain available. If the source checkout moved or a tag is unavailable, stop and resolve the source location through Copier's supported workflow rather than hand-editing lineage.

Review every change, especially dependency manifests and locks, schemas, runner commands, CI, and import rules. Resolve inline conflicts or `.rej` files deliberately. The contract rejects both forms of unresolved conflict. Do not turn a failed check into a pass by removing its validation.

If dependencies changed, use the explicit install step, then run acceptance:

```sh
./project bootstrap
./project doctor
./project check
./project test
./project build
```

Record commands, exit statuses, remaining blockers, and unrun checks in the upgrade task. Review `git diff` again, then commit the accepted update. Keep the original branch intact until review is complete. To abandon an upgrade with conflicts, retain the branch for inspection or discard only that disposable checkout after confirming no unique work is present; Copier updates do not necessarily create a Git merge that `git merge --abort` can undo.

Never use `copier recopy` as a routine upgrade, add `--trust` to bypass template review, or modify the answers file. This template uses no Copier tasks, migrations, or custom Jinja extensions. Its domain exclusions are intentional; template-managed files remain eligible for a three-way update, not guaranteed automatic reconciliation. See [Copier's update documentation](https://copier.readthedocs.io/en/stable/updating/) for the underlying behavior.

## Identity, runtime and application customization

In v0.1.1, `.project/template.json` records the generated project identity, foundation version, source ref/hash/path and runtime pins. It is consistency metadata, not a signed attestation. The driver verifies metadata/manifests/pin files against this receipt and checks the Copier answers against its source/identity fields. Normal project checks do not require the source checkout to remain available; upgrades do.

The Copier answers file is emitted as JSON, which is valid YAML and is readable before bootstrap by the standard-library runner. Copier still owns that file; do not convert or edit it manually. Keep an absolute source path when generating locally. The old v0.1.0 README's `.` source can leave broken relative lineage; if that affected an existing project, preserve its Git history and investigate a supported Copier migration against the real source before trying an update. Acceptance verifies updates from correctly recorded absolute release sources; it does not silently rewrite damaged lineage.

## Python environment contract

Since v0.1.2, bootstrap and lock validation pass both `--project` and `--directory` to uv with this repository's absolute root. The driver and Python subprocesses run isolated (`-I -B`). Process-local normalization removes inherited `PYTHON*`, active-environment pointers, and uv project/install/config-selection overrides. It does not change your shell settings. This includes `UV_NO_EDITABLE`, `UV_PROJECT`, `UV_WORKING_DIR`, `UV_FROZEN` and `UV_CONFIG_FILE`.

The explicit uv inheritance allowlist is in `.project/command_environment.py`: registry/transport settings, offline mode, concurrency, link mode and the installed Python directory remain available. New uv controls require review. Ordinary application variables are preserved. Keep intended dependency/source configuration in the project's reviewed manifests and refresh locks explicitly; do not depend on a shell variable to change what canonical acceptance runs.

Readiness requires this `.venv`, an editable root distribution whose direct URL points here, and imports resolving to `src/<package_name>`. Doctor checks the root import spec without running application initialization. The pytest wrapper also checks actual loaded project-module origins and the provenance of collected tests. Canonical Python processes use a fresh nonexistent bytecode-cache prefix with writes disabled, so old timestamp caches cannot hide a same-size source edit; no cache directory is created or deleted by this measure. Keep test callables under `tests/`; custom collectors or layout changes require updating the guard and regressions together. Installed metadata and these observations are consistency evidence, not a security boundary.

If an older environment contains a wheel or another project's installation, doctor/check/test fail without installing anything. Run the explicit `./project bootstrap` after the reviewed update, then rerun doctor/check/test/build. The normal bootstrap converts a noneditable root installation back to editable; do not hand-edit readiness state or distribution metadata.

An application's version is independent of the foundation version. Change it in its ordinary manifest and refresh the lock using `npm install --package-lock-only --ignore-scripts` or `uv lock`; review both, then explicitly run `./project bootstrap` and acceptance. Dependency additions follow the same workflow. Do not change foundation metadata to match an application release.

To change runtimes intentionally, use a reviewed branch: update the runtime receipt, the corresponding `.node-version`/`.python-version`, package-manager pin/engine constraints where applicable, and CI setup pins together. Refresh dependency locks with the chosen tools, bootstrap, then run the complete project acceptance. Record the reason in a project decision. Such changes are local customizations to managed files and may conflict on a future foundation update. Renaming a project or changing profiles needs a separate explicit migration; editing only identity metadata is not supported.

The Python identity reader supports the template's ordinary unquoted `[project]`/`name` keys and single-line quoted identity values, plus uv's generated lock syntax. Unsupported quoted/dotted identity keys or multiline TOML string forms produce an actionable failure. Full TOML and dependency validation remains uv's responsibility.
