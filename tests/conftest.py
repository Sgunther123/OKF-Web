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
