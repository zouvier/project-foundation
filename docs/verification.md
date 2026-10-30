# Verification scope

The audited v0.1.2 implementation completed 340 deterministic cases on macOS arm64 with zero failures/errors/skips. A separate bounded audit reproduced the stale-wheel, external-import, redirected-uv and timestamp-bytecode cases and found the known correctness blockers resolved. This does not establish protection against deliberately forged Python modules, plugins or reports.

The public import preserves every file under `template/` and `copier.yml` byte-for-byte from that audited baseline. Machine-specific reports, raw logs, local paths and private pilot records are excluded. [Release lineage](public-release.md) records the baseline and the public-history adjustments.

Run the complete public acceptance suite explicitly:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --python 3.13.5
mkdir -p .artifacts
FOUNDATION_INTEGRATION=1 .venv/bin/python -B -m pytest tests -q --basetemp=.artifacts/pytest
```

This performs network installation of pinned dependencies in disposable fixtures and briefly starts loopback servers. Without `FOUNDATION_INTEGRATION=1`, integration cases skip and the result is not full acceptance.

The public matrix generates two projects per profile; runs doctor/bootstrap/check/test/build and server cancellation; injects contract, type, test, mutation, environment and provenance failures; and tests source preservation, deletion, conflicts and tagged upgrades. The real-release upgrade cases start at this repository's first public tag, v0.1.2. Synthetic fixture tags continue to test multi-version updates; historical private tags are not recreated or published.

GitHub Actions runs the same suite on the pushed revision. Consult that revision's actual run result for Linux status. The historical macOS result is separate evidence. Native Windows, statistical agent-performance/cost evaluation and production deployment have not been validated. The installed-wheel workflow is separate from canonical editable-workspace acceptance. The documented plain-TOML reader restriction and upstream TestClient warning remain.
