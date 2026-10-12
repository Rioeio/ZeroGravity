from __future__ import annotations

from pathlib import Path

import yaml

import zerogravity


def test_repo_hygiene_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "LICENSE").is_file(), "LICENSE missing from repo root"
    assert (root / "SECURITY.md").is_file(), "SECURITY.md missing from repo root"
    assert (root / "CONTRIBUTING.md").is_file(), "CONTRIBUTING.md missing from repo root"
    assert (root / "src" / "zerogravity" / "py.typed").is_file(), "py.typed missing from package root"


def test_version_bump_to_0_4_0() -> None:
    assert zerogravity.__version__ == "0.4.0", f"Expected version 0.4.0, got {zerogravity.__version__}"


def test_github_workflows_and_dependabot_parse() -> None:
    root = Path(__file__).resolve().parents[2]
    release_yml = root / ".github" / "workflows" / "release.yml"
    dependabot_yml = root / ".github" / "dependabot.yml"

    assert release_yml.is_file(), ".github/workflows/release.yml missing"
    assert dependabot_yml.is_file(), ".github/dependabot.yml missing"

    release_data = yaml.safe_load(release_yml.read_text(encoding="utf-8"))
    assert "name" in release_data or True in release_data or "on" in release_data
    # Check trigger on tag v*
    triggers = release_data.get("on") or release_data.get(True)
    assert triggers is not None
    assert "push" in triggers and "tags" in triggers["push"]

    dependabot_data = yaml.safe_load(dependabot_yml.read_text(encoding="utf-8"))
    assert dependabot_data.get("version") == 2
    updates = dependabot_data.get("updates", [])
    package_ecosystems = [u.get("package-ecosystem") for u in updates]
    assert "pip" in package_ecosystems
    assert "github-actions" in package_ecosystems


def test_wheel_and_sdist_packaging() -> None:
    root = Path(__file__).resolve().parents[2]
    dist_dir = root / "dist"
    if not dist_dir.exists():
        return
    import tarfile
    import zipfile

    wheels = list(dist_dir.glob(f"*{zerogravity.__version__}*.whl"))
    sdists = list(dist_dir.glob(f"*{zerogravity.__version__}*.tar.gz"))
    if wheels:
        with zipfile.ZipFile(wheels[0]) as z:
            names = z.namelist()
            assert any("py.typed" in n for n in names)
            assert any("LICENSE" in n for n in names)
    if sdists:
        with tarfile.open(sdists[0]) as t:
            names = t.getnames()
            assert any("py.typed" in n for n in names)
            assert any("LICENSE" in n for n in names)

