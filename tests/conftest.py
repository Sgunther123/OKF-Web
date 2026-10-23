import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BUNDLE = REPO_ROOT / "bundle-example"
#: The working-state files a load or an evaluation leaves in a bundle.
WORKING_STATE = (".concepts-cache.json", ".embeddings.json")


def _working_state(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob(".*") if p.is_file() and p.name in WORKING_STATE}


@pytest.fixture(scope="session")
def example_bundle(tmp_path_factory) -> Path:
    """The example bundle, copied once per session. Loading a bundle
    writes its parse cache into it and an embedding retriever its
    vectors, so a test that read the checked-in example left working
    state in the repository (review 2026-10-21, T-U10); every test now
    reads this copy, and the checked-in tree stays as committed."""
    target = tmp_path_factory.mktemp("example") / "bundle-example"
    shutil.copytree(EXAMPLE_BUNDLE, target, ignore=shutil.ignore_patterns(*WORKING_STATE))
    return target


@pytest.fixture
def bundle_copy(tmp_path: Path, example_bundle: Path) -> Path:
    """A writable copy of the example bundle for mutation tests."""
    target = tmp_path / "bundle"
    shutil.copytree(example_bundle, target, ignore=shutil.ignore_patterns(*WORKING_STATE))
    return target


@pytest.fixture(scope="session", autouse=True)
def _the_checked_in_example_stays_as_committed():
    """Fail the session if any test wrote working state into the
    checked-in example: the reason CLAUDE.md's loop begins by deleting
    those files was that the suite used to create them."""
    before = _working_state(EXAMPLE_BUNDLE)
    yield
    written = _working_state(EXAMPLE_BUNDLE) - before
    assert not written, f"tests wrote working state into bundle-example: {sorted(written)}"


@pytest.fixture(autouse=True)
def _no_proxy_from_the_environment(monkeypatch):
    """Every socket a test opens is loopback; a proxy inherited from the
    runner's environment would route it elsewhere, or silently change
    which code path is tested (review 2026-10-21, T-U4). A test that
    wants a proxy sets one itself."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
