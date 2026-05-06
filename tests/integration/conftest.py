"""Integration test configuration: marker-driven skip + shared fixtures.

This conftest replaces the manual per-file ``pytest.mark.skipif`` boilerplate
with declarative markers that auto-skip when the required precondition is
absent. Tests apply markers via module-level ``pytestmark`` or per-test
decorators; the precondition logic lives here, exactly once.

Also exposes the ``make_copilot_project`` helper (see #1154) for tests that
need a copilot-target signal in their tmp_path scaffolding.

See microsoft/apm#1166 for the design rationale.
"""

from __future__ import annotations

import os
import platform as _platform
import shutil
import subprocess
from collections.abc import Callable
from functools import cache, lru_cache
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Binary path resolution (single source of truth for marker + fixture)
# ---------------------------------------------------------------------------


def _platform_binary_dir() -> str:
    os_name = _platform.system().lower()
    arch = _platform.machine().lower()
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    return f"apm-{os_name}-{arch_map.get(arch, arch)}"


def _resolve_apm_binary() -> Path | None:
    """Return the resolved apm binary path, or None if not found.

    Resolution order (single source of truth shared by the
    ``requires_apm_binary`` marker check and the ``apm_binary_path``
    fixture):

      1. ``APM_BINARY_PATH`` env var (CI sets this after the build step).
      2. ``shutil.which("apm")`` lookup on ``PATH``.
      3. ``./dist/apm-<os>-<arch>/apm`` (local build convention).
    """
    env_path = os.environ.get("APM_BINARY_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate.resolve()

    on_path = shutil.which("apm")
    if on_path:
        return Path(on_path).resolve()

    local_path = Path("dist") / _platform_binary_dir() / "apm"
    if local_path.is_file():
        return local_path.resolve()

    return None


# ---------------------------------------------------------------------------
# Marker precondition checks (memoized per session)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _has_github_token() -> bool:
    return bool(os.environ.get("GITHUB_APM_PAT") or os.environ.get("GITHUB_TOKEN"))


@lru_cache(maxsize=1)
def _has_ado_pat() -> bool:
    return bool(os.environ.get("ADO_APM_PAT"))


@lru_cache(maxsize=1)
def _has_ado_bearer() -> bool:
    if os.getenv("APM_TEST_ADO_BEARER") != "1":
        return False
    az_bin = shutil.which("az")
    if az_bin is None:
        return False
    try:
        result = subprocess.run(
            [
                az_bin,
                "account",
                "get-access-token",
                "--resource",
                "499b84ac-1321-427f-aa17-267ca6975798",
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0 and result.stdout.startswith("eyJ")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=1)
def _is_e2e_mode() -> bool:
    return os.environ.get("APM_E2E_TESTS", "").lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def _is_network_integration() -> bool:
    return os.environ.get("APM_RUN_INTEGRATION_TESTS") == "1"


@lru_cache(maxsize=1)
def _is_inference_mode() -> bool:
    return os.environ.get("APM_RUN_INFERENCE_TESTS") == "1"


@lru_cache(maxsize=1)
def _has_apm_binary() -> bool:
    return _resolve_apm_binary() is not None


@cache
def _has_runtime(name: str) -> bool:
    if shutil.which(name):
        return True
    runtime_path = Path.home() / ".apm" / "runtimes" / name
    return runtime_path.is_file() and os.access(runtime_path, os.X_OK)


_MARKER_CHECKS: dict[str, tuple[Callable[[], bool], str]] = {
    "requires_e2e_mode": (_is_e2e_mode, "APM_E2E_TESTS=1 not set"),
    "requires_github_token": (
        _has_github_token,
        "GITHUB_APM_PAT or GITHUB_TOKEN not set",
    ),
    "requires_ado_pat": (_has_ado_pat, "ADO_APM_PAT not set"),
    "requires_ado_bearer": (
        _has_ado_bearer,
        "az CLI + APM_TEST_ADO_BEARER=1 required",
    ),
    "requires_network_integration": (
        _is_network_integration,
        "APM_RUN_INTEGRATION_TESTS=1 not set",
    ),
    "requires_apm_binary": (
        _has_apm_binary,
        "apm binary not found (set APM_BINARY_PATH, install on PATH, or build via scripts/build-binary.sh)",
    ),
    "requires_runtime_codex": (
        lambda: _has_runtime("codex"),
        "codex runtime not available (run apm runtime setup codex)",
    ),
    "requires_runtime_copilot": (
        lambda: _has_runtime("copilot"),
        "GitHub Copilot CLI runtime not available (run apm runtime setup copilot)",
    ),
    "requires_runtime_llm": (
        lambda: _has_runtime("llm"),
        "llm runtime not available (run apm runtime setup llm)",
    ),
    "requires_inference": (
        _is_inference_mode,
        "APM_RUN_INFERENCE_TESTS=1 not set",
    ),
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip items whose marker precondition is not met.

    The skip decision is made once at collection time, so ``-v`` output shows
    the test as ``SKIPPED`` with a clear reason, exactly mirroring the prior
    ``pytestmark = pytest.mark.skipif(...)`` behavior.

    Check functions are memoized (``lru_cache``) so each precondition is
    evaluated at most once per session, regardless of how many tests carry
    the marker. We also short-circuit per item once the first failing
    precondition fires, to avoid evaluating later checks for an item we
    have already decided to skip.
    """
    for item in items:
        for marker_name, (check_fn, reason) in _MARKER_CHECKS.items():
            if item.get_closest_marker(marker_name) and not check_fn():
                item.add_marker(pytest.mark.skip(reason=reason))
                break


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def apm_binary_path() -> Path:
    """Resolve the apm binary path for tests that shell out to it.

    Uses the same resolution chain as the ``requires_apm_binary`` marker
    (see ``_resolve_apm_binary``). Skips the test if no binary is found.
    """
    resolved = _resolve_apm_binary()
    if resolved is None:
        pytest.skip(
            "No apm binary found "
            "(set APM_BINARY_PATH, install on PATH, or build via scripts/build-binary.sh)"
        )
    return resolved  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Shared helpers (carried in from main #1154)
# ---------------------------------------------------------------------------


def make_copilot_project(tmp_path: Path, name: str = "test-project") -> Path:
    """Create a temp project with a valid copilot signal.

    Materializes ``<tmp_path>/<name>/.github/copilot-instructions.md`` so
    auto-detection resolves to the copilot target without ambiguity.

    Args:
        tmp_path: pytest ``tmp_path`` fixture.
        name: Project directory name (default ``"test-project"``).

    Returns:
        The created project root.
    """
    project = tmp_path / name
    project.mkdir()
    github_dir = project / ".github"
    github_dir.mkdir()
    (github_dir / "copilot-instructions.md").write_bytes(b"# Copilot instructions\n")
    return project
