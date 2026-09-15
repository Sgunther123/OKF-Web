"""EDGE-CASES phase E1: guardrails against data loss and mis-scoping.

Covers U1 (`publish` deletes whatever the dist names), U2 (a missing
bundle path is a clean bundle), A1 (a dist inside the bundle loads as
concepts), U8 (operator files get published), S4 (symlinks followed)
and S10 (`verify` reads manifest paths without containment).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from okf_web import cli as cli_mod
from okf_web.model import DIST_MARKER, BundleNotFound, load_bundle
from okf_web.publisher import PublishError, UnsafeDist, check_dist, publish
from okf_web.signing import verify_integrity
from okf_web.viewer import ViewerError, write_viewer


def _tree(root: Path) -> set[str]:
    """Every visible file under root (the parse cache is a dotfile and
    may appear at any time; it is working state, not content)."""
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)
    }


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):  # pragma: no cover - platform
        pytest.skip("symlinks unavailable on this platform")


# --- U1: the dist is never the bundle, its parent, or a stranger -------

def test_publish_refuses_the_bundle_itself(bundle_copy):
    before = _tree(bundle_copy)
    with pytest.raises(UnsafeDist, match="into the bundle itself"):
        publish(bundle_copy, bundle_copy)
    assert _tree(bundle_copy) == before


def test_publish_refuses_a_dist_inside_the_bundle(bundle_copy):
    before = _tree(bundle_copy)
    with pytest.raises(UnsafeDist, match="into the bundle itself"):
        publish(bundle_copy, bundle_copy / "dist")
    assert not (bundle_copy / "dist").exists()
    assert _tree(bundle_copy) == before


def test_publish_refuses_a_dist_that_contains_the_bundle(bundle_copy, tmp_path):
    before = _tree(bundle_copy)
    with pytest.raises(UnsafeDist, match="contains the bundle"):
        publish(bundle_copy, tmp_path)
    assert _tree(bundle_copy) == before


def test_publish_refuses_a_foreign_directory_unless_forced(bundle_copy, tmp_path):
    stranger = tmp_path / "photos"
    stranger.mkdir()
    (stranger / "holiday.jpg").write_bytes(b"\xff\xd8")
    with pytest.raises(UnsafeDist, match="--force"):
        publish(bundle_copy, stranger)
    assert (stranger / "holiday.jpg").exists()
    result = publish(bundle_copy, stranger, force=True)
    assert not (stranger / "holiday.jpg").exists()
    assert (stranger / "manifest.json").exists()
    assert result.published


def test_republish_into_a_previous_dist_needs_no_force(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    first = publish(bundle_copy, dist)
    second = publish(bundle_copy, dist)
    assert sorted(second.published) == sorted(first.published)


def test_publish_refuses_a_dist_path_that_is_a_file(bundle_copy, tmp_path):
    blob = tmp_path / "dist"
    blob.write_text("not a directory", encoding="utf-8")
    with pytest.raises(UnsafeDist, match="not a directory"):
        publish(bundle_copy, blob)
    assert blob.read_text(encoding="utf-8") == "not a directory"


def test_check_dist_resolves_relative_paths(bundle_copy, tmp_path, monkeypatch):
    monkeypatch.chdir(bundle_copy)
    with pytest.raises(UnsafeDist):
        check_dist(".", "dist")  # inside the bundle, spelled relatively
    with pytest.raises(UnsafeDist):
        check_dist(".", "..")  # the parent, spelled relatively
    check_dist(".", tmp_path / "elsewhere")  # does not exist yet: fine


# --- A1: a published copy inside the bundle is never knowledge ---------

def test_dist_carries_a_marker_outside_the_manifest(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    assert (dist / DIST_MARKER).is_file()
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    assert DIST_MARKER not in manifest["files"]
    assert verify_integrity(dist) == ([], [])
    # A dist loaded on purpose (verify, discover, tests) still reads as
    # a bundle: the marker at the root is not a "skip me".
    assert load_bundle(dist).concepts


def test_loader_and_publisher_skip_a_dist_left_inside_the_bundle(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    expected = set(load_bundle(bundle_copy).concepts)
    shutil.copytree(dist, bundle_copy / "old-dist")

    bundle = load_bundle(bundle_copy)
    assert set(bundle.concepts) == expected
    assert not any(rel.startswith("old-dist/") for rel in bundle.indexes)

    result = publish(bundle_copy, tmp_path / "dist2")
    assert not any(rel.startswith("old-dist/") for rel in result.published)
    assert not any(rel.startswith("old-dist/") for rel in result.assets)
    assert not (tmp_path / "dist2" / "old-dist").exists()
    assert [w for w in result.warnings if "old-dist/ is a published copy" in w]


# --- S4: symlinks are never bundle content -----------------------------

def test_loader_and_publisher_skip_symlinks(bundle_copy, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text(
        (bundle_copy / "faq" / "general.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _symlink(secret, bundle_copy / "faq" / "leak.md")
    _symlink(outside, bundle_copy / "linked-dir")

    bundle = load_bundle(bundle_copy)
    assert "faq/leak.md" not in bundle.concepts
    assert not any(rel.startswith("linked-dir/") for rel in bundle.concepts)

    dist = tmp_path / "dist"
    result = publish(bundle_copy, dist)
    assert "faq/leak.md" not in result.published
    assert not (dist / "faq" / "leak.md").exists()
    assert not (dist / "linked-dir").exists()
    assert any("faq/leak.md is a symlink" in w for w in result.warnings)
    assert any("linked-dir is a symlink" in w for w in result.warnings)


# --- U8: operator files stay out; shipped assets are named -------------

def test_publish_skips_operator_files_and_names_assets(bundle_copy, tmp_path, capsys):
    (bundle_copy / "bundle-viewer.html").write_text("<p>viewer</p>", encoding="utf-8")
    (bundle_copy / "feeds").mkdir()
    (bundle_copy / "feeds" / "products.csv").write_text("sku,price\nA,1\n", encoding="utf-8")
    (bundle_copy / "export.TSV").write_text("sku\tprice\n", encoding="utf-8")

    dist = tmp_path / "dist"
    result = publish(bundle_copy, dist)
    for rel in ("bundle-viewer.html", "feeds/products.csv", "export.TSV"):
        assert rel not in result.published
        assert not (dist / rel).exists()
        assert any(rel in w and "operator file" in w for w in result.warnings)
    assert result.assets == ["attesters/http_refetch.py", "evaluations/questions.yaml"]

    assert cli_mod.main(["publish", str(bundle_copy), str(tmp_path / "dist2")]) == 0
    out = capsys.readouterr().out
    assert (
        "shipped 2 non-concept asset(s): attesters/http_refetch.py, "
        "evaluations/questions.yaml" in out
    )


# --- U2: a missing bundle is an error, never an empty bundle -----------

def test_missing_bundle_raises_bundle_not_found(tmp_path):
    with pytest.raises(BundleNotFound, match="bundle directory not found"):
        load_bundle(tmp_path / "nope")
    assert issubclass(BundleNotFound, FileNotFoundError)


@pytest.mark.parametrize(
    "argv",
    [
        ["lint", "{missing}"],
        ["lint", "{missing}", "--strict"],
        ["review", "list", "{missing}"],
        ["drift", "{missing}"],
        ["publish", "{missing}", "{dist}"],
        ["evaluate", "{missing}", "--dry-run"],
        ["view", "{missing}", "--out", "{viewer}"],
    ],
)
def test_cli_maps_a_missing_bundle_to_exit_2(argv, tmp_path, capsys):
    missing = tmp_path / "typo-store"
    dist = tmp_path / "dist"
    viewer = tmp_path / "viewer.html"
    argv = [a.format(missing=missing, dist=dist, viewer=viewer) for a in argv]
    assert cli_mod.main(argv) == 2
    captured = capsys.readouterr()
    assert str(missing) in captured.err
    assert "0 error(s)" not in captured.out
    assert not dist.exists() and not viewer.exists()


def test_publish_refuses_an_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(PublishError, match="nothing to publish"):
        publish(empty, tmp_path / "dist")
    assert not (tmp_path / "dist").exists()


# --- S10: verify contains manifest paths -------------------------------

def test_verify_integrity_rejects_paths_outside_the_dist(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    outside = tmp_path / "outside.txt"
    outside.write_text("not yours", encoding="utf-8")
    _symlink(outside, dist / "link.txt")

    manifest_path = dist / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = {"sha256": "0" * 64, "bytes": 8}
    manifest["files"]["../outside.txt"] = entry
    manifest["files"][str(outside)] = entry
    manifest["files"]["jsonld/../../outside.txt"] = entry
    manifest["files"]["link.txt"] = entry
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors, _ = verify_integrity(dist)
    assert len(errors) == 4
    assert all(e.startswith("invalid manifest path") for e in errors)
    assert any("escapes the dist" in e and "link.txt" in e for e in errors)


def test_verify_integrity_rejects_a_directory_entry(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    manifest_path = dist / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["jsonld"] = {"sha256": "0" * 64, "bytes": 1}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    errors, _ = verify_integrity(dist)
    assert errors == ["not a regular file: jsonld"]


# --- the viewer page stays outside the bundle --------------------------

def test_viewer_refuses_an_output_inside_the_bundle(bundle_copy, tmp_path, capsys, monkeypatch):
    with pytest.raises(ViewerError, match="inside the bundle"):
        write_viewer(bundle_copy, out=bundle_copy / "bundle-viewer.html")
    assert not (bundle_copy / "bundle-viewer.html").exists()

    nested = bundle_copy / "sub" / "v.html"
    assert cli_mod.main(["view", str(bundle_copy), "--out", str(nested)]) == 2
    assert "inside the bundle" in capsys.readouterr().err
    assert not nested.parent.exists()

    # The default output is the working directory, which is refused
    # only when the working directory is the bundle.
    monkeypatch.chdir(bundle_copy)
    assert cli_mod.main(["view", "."]) == 2
    assert not (bundle_copy / "bundle-viewer.html").exists()
    monkeypatch.chdir(tmp_path)
    assert cli_mod.main(["view", str(bundle_copy)]) == 0
    assert (tmp_path / "bundle-viewer.html").exists()


# --- CLI: --force on publish and init ----------------------------------

def test_cli_publish_force(bundle_copy, tmp_path, capsys):
    stranger = tmp_path / "www"
    stranger.mkdir()
    (stranger / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    assert cli_mod.main(["publish", str(bundle_copy), str(stranger)]) == 2
    assert "refusing to empty" in capsys.readouterr().err
    assert (stranger / "index.html").exists()
    assert cli_mod.main(["publish", str(bundle_copy), str(stranger), "--force"]) == 0
    assert not (stranger / "index.html").exists()
    assert (stranger / "manifest.json").exists()


def test_cli_publish_into_the_bundle_exits_2_and_keeps_every_file(bundle_copy, capsys):
    before = _tree(bundle_copy)
    assert cli_mod.main(["publish", str(bundle_copy), str(bundle_copy)]) == 2
    assert "into the bundle itself" in capsys.readouterr().err
    assert _tree(bundle_copy) == before
    # --force never overrides this one.
    assert cli_mod.main(["publish", str(bundle_copy), str(bundle_copy), "--force"]) == 2
    assert _tree(bundle_copy) == before


def test_init_parser_accepts_force():
    parser = cli_mod.build_parser()
    assert parser.parse_args(["init", "store", "--feed", "p.csv", "--force"]).force is True
    assert parser.parse_args(["init", "store", "--feed", "p.csv"]).force is False
