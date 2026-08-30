from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path
from typing import Any

from zerogravity.parsers.base import (
    BaseParser,
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)


def _extract_rust_workspace_info(path: Path, data: dict[str, Any]) -> tuple[list[Path], set[str]]:
    """Extract workspace member paths and package names from Cargo.toml."""
    member_paths: set[Path] = set()
    member_names: set[str] = set()

    ws = data.get("workspace")
    if isinstance(ws, dict):
        members = ws.get("members", [])
        exclude = ws.get("exclude", [])
        if isinstance(members, list):
            inclusion_patterns = [p for p in members if isinstance(p, str) and not p.startswith("!")]
            exclusion_patterns = [p[1:] if p.startswith("!") else p for p in (exclude if isinstance(exclude, list) else [])]

            for pat in inclusion_patterns:
                clean_pat = pat.lstrip("./").strip("/")
                if not clean_pat:
                    continue
                try:
                    for p in path.glob(clean_pat):
                        if p.is_dir() and (p / "Cargo.toml").is_file() and p.resolve() != path.resolve():
                            rel = p.relative_to(path).as_posix()
                            excluded = False
                            for expat in exclusion_patterns:
                                clean_expat = expat.lstrip("./").strip("/")
                                if fnmatch.fnmatch(rel, clean_expat) or fnmatch.fnmatch(p.name, clean_expat):
                                    excluded = True
                                    break
                            if not excluded:
                                member_paths.add(p.resolve())
                except Exception:
                    pass

    return sorted(list(member_paths)), member_names


def _find_rust_workspace_root(path: Path) -> tuple[Path, list[Path]] | None:
    """Find ancestor directory that defines a Cargo workspace containing this path."""
    current = path.resolve().parent
    while current != current.parent:
        cargo_toml = current / "Cargo.toml"
        if cargo_toml.is_file():
            try:
                with open(cargo_toml, "rb") as f:
                    data = tomllib.load(f)
                members, _ = _extract_rust_workspace_info(current, data)
                if path.resolve() in members:
                    return current, members
            except Exception:
                pass
        if (current / ".git").is_dir():
            break
        current = current.parent
    return None


def _get_rust_member_names(member_paths: list[Path]) -> set[str]:
    """Read crate names from member Cargo.toml files."""
    names: set[str] = set()
    for mp in member_paths:
        ct = mp / "Cargo.toml"
        if ct.is_file():
            try:
                with open(ct, "rb") as f:
                    data = tomllib.load(f)
                pkg = data.get("package")
                if isinstance(pkg, dict) and "name" in pkg and isinstance(pkg["name"], str):
                    names.add(pkg["name"])
            except Exception:
                pass
    return names


class RustParser(BaseParser):
    """
    Parser for Rust projects (Cargo.toml and Cargo.lock).
    """

    @property
    def ecosystem(self) -> Ecosystem:
        """Return the ecosystem for this parser."""
        return Ecosystem.RUST

    def can_parse(self, path: Path) -> bool:
        """Check if Cargo.toml exists in the directory."""
        return (path / "Cargo.toml").is_file()

    def _parse_dep_spec(
        self,
        name: str,
        spec: Any,
        source: str,
        default_type: DependencyType,
    ) -> Dependency:
        """Parse a single dependency declaration from Cargo.toml."""
        if isinstance(spec, str):
            return Dependency(
                name=name,
                version_spec=spec,
                resolved_version=None,
                dep_type=default_type,
                extras=[],
                source=source,
                metadata={},
            )

        if isinstance(spec, dict):
            version_spec = spec.get("version")
            raw_features = spec.get("features", [])
            extras = [str(f) for f in raw_features] if isinstance(raw_features, list) else []

            is_optional = spec.get("optional") is True
            dep_type = DependencyType.OPTIONAL if is_optional else default_type

            meta: dict[str, Any] = {}
            if is_optional:
                meta["optional"] = True

            if "path" in spec:
                meta["path"] = str(spec["path"])
                meta["workspace_internal"] = True
                if not version_spec:
                    version_spec = str(spec["path"])

            if "git" in spec:
                meta["git"] = str(spec["git"])
                if not version_spec:
                    version_spec = str(spec["git"])

            if "branch" in spec:
                meta["branch"] = str(spec["branch"])
            if "tag" in spec:
                meta["tag"] = str(spec["tag"])
            if "rev" in spec:
                meta["rev"] = str(spec["rev"])

            if spec.get("workspace") is True:
                meta["workspace"] = True
                if not version_spec:
                    version_spec = "*"

            if "default-features" in spec:
                meta["default-features"] = spec["default-features"]
            if "default_features" in spec:
                meta["default_features"] = spec["default_features"]
            if "package" in spec:
                meta["package"] = str(spec["package"])

            if not version_spec:
                version_spec = "*"

            return Dependency(
                name=name,
                version_spec=str(version_spec),
                resolved_version=None,
                dep_type=dep_type,
                extras=extras,
                source=source,
                metadata=meta,
            )

        return Dependency(
            name=name,
            version_spec="*",
            resolved_version=None,
            dep_type=default_type,
            extras=[],
            source=source,
            metadata={},
        )

    def _collect_dependencies(
        self,
        table: dict[str, Any],
        source: str,
    ) -> list[Dependency]:
        """Collect dependencies from dependencies, dev-dependencies, build-dependencies, and targets."""
        deps: list[Dependency] = []

        sections = [
            ("dependencies", DependencyType.PRODUCTION),
            ("dev-dependencies", DependencyType.DEVELOPMENT),
            ("dev_dependencies", DependencyType.DEVELOPMENT),
            ("build-dependencies", DependencyType.BUILD),
            ("build_dependencies", DependencyType.BUILD),
        ]

        # Top-level dependencies
        for sec_name, dep_type in sections:
            sec_data = table.get(sec_name)
            if isinstance(sec_data, dict):
                for name, spec in sec_data.items():
                    deps.append(self._parse_dep_spec(name, spec, source, dep_type))

        # Target-specific dependencies
        targets = table.get("target")
        if isinstance(targets, dict):
            for target_cfg, target_table in targets.items():
                if isinstance(target_table, dict):
                    for sec_name, dep_type in sections:
                        sec_data = target_table.get(sec_name)
                        if isinstance(sec_data, dict):
                            for name, spec in sec_data.items():
                                dep = self._parse_dep_spec(name, spec, source, dep_type)
                                dep.metadata["target"] = target_cfg
                                deps.append(dep)

        return deps

    def parse(self, path: Path) -> ProjectManifest:
        """
        Parse Cargo.toml and Cargo.lock files.
        """
        path = path.resolve()
        cargo_toml_path = path / "Cargo.toml"

        if not cargo_toml_path.is_file():
            raise FileNotFoundError(f"Cargo.toml not found in {path}")

        try:
            with open(cargo_toml_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Malformed TOML in {cargo_toml_path}: {e}")
        except OSError as e:
            raise IOError(f"Could not read {cargo_toml_path}: {e}")

        package_data = data.get("package", {})
        if not isinstance(package_data, dict):
            package_data = {}

        project_name = package_data.get("name", path.name)
        engine_constraints: dict[str, str] = {}
        metadata: dict[str, Any] = {}

        # Rust version extraction (rust-version or rust_version in [package] or [workspace.package])
        rust_version = package_data.get("rust-version") or package_data.get("rust_version")
        if not rust_version and "workspace" in data and isinstance(data["workspace"], dict):
            ws_pkg = data["workspace"].get("package", {})
            if isinstance(ws_pkg, dict):
                rust_version = ws_pkg.get("rust-version") or ws_pkg.get("rust_version")

        if rust_version:
            engine_constraints["rust"] = str(rust_version)

        # Edition extraction
        edition = package_data.get("edition")
        if not edition and "workspace" in data and isinstance(data["workspace"], dict):
            ws_pkg = data["workspace"].get("package", {})
            if isinstance(ws_pkg, dict):
                edition = ws_pkg.get("edition")

        if edition:
            metadata["edition"] = str(edition)

        # Direct dependencies
        dependencies = self._collect_dependencies(data, "Cargo.toml")
        manifest_files: list[Path] = [cargo_toml_path]

        # Workspace detection
        is_workspace_root = False
        is_workspace_member = False
        workspace_root: Path | None = None
        workspace_members: list[Path] = []
        workspace_member_names: set[str] = set()

        members, names = _extract_rust_workspace_info(path, data)
        if members or ("workspace" in data and isinstance(data["workspace"], dict)):
            is_workspace_root = True
            workspace_root = path
            workspace_members = members
            workspace_member_names = names | _get_rust_member_names(members)
        else:
            ancestor_info = _find_rust_workspace_root(path)
            if ancestor_info:
                is_workspace_member = True
                workspace_root, workspace_members = ancestor_info
                workspace_member_names = _get_rust_member_names(workspace_members)
            else:
                has_sibling_path_dep = any(
                    isinstance(d.metadata.get("path"), str) and d.metadata["path"].startswith("..")
                    for d in dependencies
                )
                if has_sibling_path_dep:
                    is_workspace_member = True
                    workspace_root = path.parent

        # Mark workspace-internal dependencies
        for dep in dependencies:
            if (
                dep.name in workspace_member_names
                or dep.metadata.get("workspace_internal")
                or (isinstance(dep.metadata.get("path"), str) and dep.metadata["path"].startswith("."))
            ):
                dep.metadata["workspace_internal"] = True

        # Lockfile detection (check local directory first, then workspace root)
        lockfile_present = False
        lockfile_path: Path | None = None

        if (path / "Cargo.lock").is_file():
            lockfile_present = True
            lockfile_path = path / "Cargo.lock"
        elif workspace_root and (workspace_root / "Cargo.lock").is_file():
            lockfile_present = True
            lockfile_path = workspace_root / "Cargo.lock"

        if lockfile_present and lockfile_path:
            manifest_files.append(lockfile_path)
            try:
                with open(lockfile_path, "rb") as f:
                    lock_data = tomllib.load(f)

                resolved_map: dict[str, str] = {}
                lock_packages = lock_data.get("package", [])
                if isinstance(lock_packages, list):
                    for pkg in lock_packages:
                        if isinstance(pkg, dict):
                            pname = pkg.get("name")
                            pversion = pkg.get("version")
                            if pname and pversion and isinstance(pname, str) and isinstance(pversion, str):
                                resolved_map[pname] = pversion

                # Update direct dependencies with resolved versions
                direct_dep_names = {dep.name for dep in dependencies}
                for dep in dependencies:
                    if dep.name in resolved_map:
                        dep.resolved_version = resolved_map[dep.name]

                # Add transitive dependencies
                excluded_names = direct_dep_names | workspace_member_names
                if project_name:
                    excluded_names.add(project_name)

                transitive_seen: set[str] = set()
                if isinstance(lock_packages, list):
                    for pkg in lock_packages:
                        if isinstance(pkg, dict):
                            pname = pkg.get("name")
                            pversion = pkg.get("version")
                            if (
                                pname
                                and pversion
                                and isinstance(pname, str)
                                and isinstance(pversion, str)
                                and pname not in excluded_names
                                and pname not in transitive_seen
                            ):
                                transitive_seen.add(pname)
                                dependencies.append(
                                    Dependency(
                                        name=pname,
                                        version_spec=pversion,
                                        resolved_version=pversion,
                                        dep_type=DependencyType.PRODUCTION,
                                        extras=[],
                                        source="Cargo.lock",
                                        metadata={"transitive": True},
                                    )
                                )
            except (tomllib.TOMLDecodeError, OSError):
                pass

        return ProjectManifest(
            project_path=path,
            project_name=project_name,
            ecosystem=self.ecosystem,
            dependencies=dependencies,
            engine_constraints=engine_constraints,
            lockfile_present=lockfile_present,
            lockfile_path=lockfile_path,
            manifest_files=manifest_files,
            metadata=metadata,
            workspace_root=workspace_root,
            workspace_members=workspace_members,
            is_workspace_root=is_workspace_root,
            is_workspace_member=is_workspace_member,
        )
