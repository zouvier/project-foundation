"""Process-local defaults for the canonical workflow, never shell settings.

uv's project/install selection belongs to this repository. Only explicit
transport, registry, cache-link and concurrency controls are inherited; new uv
options require review rather than silently changing which project is prepared.
"""
from pathlib import Path
import re


UV_INHERITED = {
    "UV_OFFLINE", "UV_LINK_MODE", "UV_CONCURRENT_BUILDS", "UV_CONCURRENT_DOWNLOADS",
    "UV_CONCURRENT_INSTALLS", "UV_HTTP_TIMEOUT", "UV_HTTP_CONNECT_TIMEOUT", "UV_HTTP_RETRIES",
    "UV_INDEX", "UV_DEFAULT_INDEX", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL", "UV_INDEX_STRATEGY",
    "UV_FIND_LINKS", "UV_NO_INDEX", "UV_KEYRING_PROVIDER", "UV_CREDENTIALS_DIR",
    "UV_SYSTEM_CERTS", "UV_NATIVE_TLS", "UV_NO_PROGRESS", "UV_PYTHON_INSTALL_DIR",
}
NPM_REMOVED = {
    "npm_config_production", "npm_config_omit", "npm_config_only",
    "npm_config_include", "npm_config_prefix", "node_options",
}


def command_environment(root: Path, inherited: dict[str, str]) -> dict[str, str]:
    """Drop interpreter/project/install overrides, preserving ordinary app env."""
    env = {}
    for key, value in inherited.items():
        if key.startswith("PYTHON") or key in {"VIRTUAL_ENV", "CONDA_PREFIX", "__PYVENV_LAUNCHER__"}:
            continue
        if key.startswith("UV_") and key not in UV_INHERITED and not re.fullmatch(
            r"UV_INDEX_[A-Z0-9_]+_(?:USERNAME|PASSWORD)", key
        ):
            continue
        if key.lower() not in NPM_REMOVED:
            env[key] = value
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1",
        "UV_CACHE_DIR": str(root / ".cache/uv"), "UV_PROJECT_ENVIRONMENT": str(root / ".venv"),
        "UV_PYTHON_DOWNLOADS": "never", "UV_NO_ENV_FILE": "1",
        "npm_config_cache": str(root / ".cache/npm"), "npm_config_global": "false",
    })
    return env
