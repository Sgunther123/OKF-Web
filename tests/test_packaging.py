"""Review 2026-10-21, phase U2 (T-U5): the wheel ships the prompts and
the question packs. Editable installs hide a wrong package-data glob;
the built distribution does not."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("build") is None, reason="python -m build is not installed"
)


def test_wheel_ships_prompts_and_question_packs(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    wheel = next(tmp_path.glob("okf_web-*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    prompts = sorted(p.name for p in (REPO_ROOT / "src/okf_web/prompts").glob("*.md"))
    packs = sorted(p.name for p in (REPO_ROOT / "src/okf_web/questionpacks").glob("*.yaml"))
    assert len(prompts) == 4 and len(packs) == 10
    for name in prompts:
        assert f"okf_web/prompts/{name}" in names
    for name in packs:
        assert f"okf_web/questionpacks/{name}" in names
