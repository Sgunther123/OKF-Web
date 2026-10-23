import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BUNDLE = REPO_ROOT / "bundle-example"


@pytest.fixture
def example_bundle() -> Path:
    return EXAMPLE_BUNDLE


@pytest.fixture
def bundle_copy(tmp_path: Path) -> Path:
    """A writable copy of the example bundle for mutation tests."""
    target = tmp_path / "bundle"
    shutil.copytree(EXAMPLE_BUNDLE, target)
    return target


@pytest.fixture(autouse=True)
def _no_proxy_from_the_environment(monkeypatch):
    """Every socket a test opens is loopback; a proxy inherited from the
    runner's environment would route it elsewhere, or silently change
    which code path is tested (review 2026-10-21, T-U4). A test that
    wants a proxy sets one itself."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
