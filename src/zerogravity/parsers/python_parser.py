from __future__ import annotations

import re
import tomllib
from pathlib import Path

from zerogravity.parsers.base import (
    BaseParser,
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)


def _extract_python_workspace_info(path: Path, data: dict) -> tuple[list[Path], set[str]]:
    """Extract workspace member paths and package names from pyproject.toml."""
    member_paths: set[Path] = set()
    member_names: set[str] = set()

    # 1. tool.uv.workspace members
    if "tool" in data and isinstance(data["tool"], dict):
        uv_cfg = data["tool"].get("uv", {})
        if isinstance(uv_cfg, dict) and "workspace" in uv_cfg:
            ws = uv_cfg["workspace"]
            members = ws.get("members", []) if isinstance(ws, dict) else []
            for pat in members:
                clean_pat = pat.lstrip("./").strip("/")
                try:
                    for p in path.glob(clean_pat):
                        if p.is_dir() and ((p / "pyproject.toml").is_file() or (p / "setup.py").is_file()):
                            if p.resolve() != path.resolve():
                                member_paths.add(p.resolve())
                except Exception:
                    pass

    # Helper for path dependency inspection
    resolved_root = path.resolve()

    def _check_dep_string(dep_str: str) -> None:
        if "@" in dep_str:
            parts = dep_str.split("@", 1)
            pkg_name = parts[0].strip()
            loc = parts[1].strip()
            if loc.startswith("file:") or loc.startswith(".") or "/" in loc or "\\" in loc:
                clean_loc = loc.removeprefix("file://").removeprefix("file:").strip()
                try:
                    target_path = (path / clean_loc).resolve()
                    if (
                        target_path.is_dir()
                        and ((target_path / "pyproject.toml").is_file() or (target_path / "setup.py").is_file())
                        and target_path != resolved_root
                        and target_path.is_relative_to(resolved_root)
                    ):
                        member_paths.add(target_path)
                        member_names.add(pkg_name)
                except Exception:
                    pass

    # 2. PEP 621 dependencies & optional-dependencies
    if "project" in data and isinstance(data["project"], dict):
        for req in data["project"].get("dependencies", []):
            if isinstance(req, str):
                _check_dep_string(req)
        for reqs in data["project"].get("optional-dependencies", {}).values():
            if isinstance(reqs, list):
                for req in reqs:
                    if isinstance(req, str):
                        _check_dep_string(req)

    # 3. Poetry dependencies
    if "tool" in data and isinstance(data["tool"], dict) and "poetry" in data["tool"]:
        poetry_deps = data["tool"]["poetry"].get("dependencies", {})
        if isinstance(poetry_deps, dict):
            for name, spec in poetry_deps.items():
                if isinstance(spec, dict) and "path" in spec:
                    try:
                        target_path = (path / spec["path"]).resolve()
                        if (
                            target_path.is_dir()
                            and ((target_path / "pyproject.toml").is_file() or (target_path / "setup.py").is_file())
                            and target_path != resolved_root
                            and target_path.is_relative_to(resolved_root)
                        ):
                            member_paths.add(target_path)
                            member_names.add(name)
                    except Exception:
                        pass

    return sorted(list(member_paths)), member_names


def _find_python_workspace_root(path: Path) -> tuple[Path, list[Path]] | None:
    """Find ancestor directory that defines a workspace containing this path."""
    current = path.resolve().parent
    while current != current.parent:
        pyproject = current / "pyproject.toml"
        if pyproject.is_file():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                members, _ = _extract_python_workspace_info(current, data)
                if path.resolve() in members:
                    return current, members
            except Exception:
                pass
        if (current / ".git").is_dir():
            break
        current = current.parent
    return None


def _get_python_member_names(member_paths: list[Path]) -> set[str]:
    """Read package names from member pyproject.toml files."""
    names: set[str] = set()
    for mp in member_paths:
        pyp = mp / "pyproject.toml"
        if pyp.is_file():
            try:
                with open(pyp, "rb") as f:
                    data = tomllib.load(f)
                if "project" in data and "name" in data["project"]:
                    names.add(data["project"]["name"])
                elif "tool" in data and "poetry" in data["tool"] and "name" in data["tool"]["poetry"]:
                    names.add(data["tool"]["poetry"]["name"])
            except Exception:
                pass
    return names


class PythonParser(BaseParser):
    """
    Parser for Python projects (requirements.txt, pyproject.toml, Pipfile).
    """

    @property
    def ecosystem(self) -> Ecosystem:
        """Return the ecosystem for this parser."""
        return Ecosystem.PYTHON

    def can_parse(self, path: Path) -> bool:
        """Check if any Python manifest files exist."""
        manifests = ["requirements.txt", "pyproject.toml", "Pipfile"]
        return any((path / m).is_file() for m in manifests)

    def _parse_pep508_req(self, req_str: str, source: str, dep_type: DependencyType) -> Dependency:
        """Basic parser for PEP 508 requirement strings."""
        marker = None
        if ";" in req_str:
            req_str, marker = req_str.split(";", 1)
            marker = marker.strip()

        req_str = req_str.strip()

        # Handle direct reference URL/path dependencies (e.g. pkg @ file:../pkg or pkg @ ./pkg)
        if " @ " in req_str:
            name, loc = req_str.split(" @ ", 1)
            name = name.strip()
            loc = loc.strip()
            is_internal = loc.startswith("file:") or loc.startswith(".") or "/" in loc or "\\" in loc
            meta: dict = {"path": loc} if is_internal else {}
            if marker:
                meta["marker"] = marker
            if is_internal:
                meta["workspace_internal"] = True
            return Dependency(
                name=name,
                version_spec=loc,
                resolved_version=None,
                dep_type=dep_type,
                extras=[],
                source=source,
                metadata=meta,
            )

        # Handle VCS
        if req_str.startswith("git+") or req_str.startswith("hg+") or req_str.startswith("svn+") or req_str.startswith("bzr+"):
            name = req_str
            if "#egg=" in req_str:
                name = req_str.split("#egg=")[-1].split("&")[0]
            return Dependency(
                name=name,
                version_spec=req_str,
                resolved_version=None,
                dep_type=dep_type,
                extras=[],
                source=source,
                metadata={"marker": marker} if marker else {}
            )

        # Match name, extras, version
        match = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:\[([^\]]+)\])?(.*)$", req_str)
        if not match:
            # Fallback
            return Dependency(
                name=req_str,
                version_spec="*",
                resolved_version=None,
                dep_type=dep_type,
                extras=[],
                source=source,
                metadata={"marker": marker} if marker else {}
            )

        name = match.group(1)
        extras_str = match.group(2)
        version_spec = match.group(3).strip()

        extras = [e.strip() for e in extras_str.split(",")] if extras_str else []
        if not version_spec:
            version_spec = "*"

        return Dependency(
            name=name,
            version_spec=version_spec,
            resolved_version=None,
            dep_type=dep_type,
            extras=extras,
            source=source,
            metadata={"marker": marker} if marker else {}
        )

    def _parse_requirements_txt(self, path: Path) -> tuple[list[Dependency], dict]:
        """Parse requirements.txt and return dependencies, includes, and metadata."""
        deps = []
        includes = []
        metadata = {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if line.startswith("-r ") or line.startswith("--requirement "):
                        include_file = line.split(" ", 1)[1].strip()
                        includes.append(include_file)
                        continue

                    if line.startswith("-"):
                        continue

                    dep = self._parse_pep508_req(line, path.name, DependencyType.PRODUCTION)
                    deps.append(dep)
        except OSError:
            pass

        if includes:
            metadata["includes"] = includes

        return deps, metadata

    def _parse_pyproject_toml(self, path: Path) -> tuple[str | None, dict[str, str], list[Dependency], bool, dict]:
        """Parse pyproject.toml."""
        project_name: str | None = None
        engine_constraints: dict[str, str] = {}
        deps: list[Dependency] = []
        poetry_lock = False
        raw_data: dict = {}

        try:
            with open(path, "rb") as f:
                raw_data = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError):
            return project_name, engine_constraints, deps, poetry_lock, raw_data

        if "project" in raw_data:
            project_data = raw_data["project"]
            project_name = project_data.get("name")

            if "requires-python" in project_data:
                engine_constraints["python"] = project_data["requires-python"]

            for req in project_data.get("dependencies", []):
                deps.append(self._parse_pep508_req(req, path.name, DependencyType.PRODUCTION))

            optional = project_data.get("optional-dependencies", {})
            for group, reqs in optional.items():
                for req in reqs:
                    dep = self._parse_pep508_req(req, path.name, DependencyType.OPTIONAL)
                    dep.metadata["optional_group"] = group
                    deps.append(dep)

        elif "tool" in raw_data and "poetry" in raw_data["tool"]:
            poetry_data = raw_data["tool"]["poetry"]
            project_name = poetry_data.get("name")

            poetry_deps = poetry_data.get("dependencies", {})
            for name, spec in poetry_deps.items():
                if name == "python":
                    engine_constraints["python"] = spec if isinstance(spec, str) else spec.get("version", "*")
                    continue

                dep_meta: dict = {}
                if isinstance(spec, dict) and "path" in spec:
                    version_spec = spec.get("version") or spec["path"]
                    dep_meta["path"] = spec["path"]
                    dep_meta["workspace_internal"] = True
                else:
                    version_spec = spec if isinstance(spec, str) else spec.get("version", "*")

                deps.append(Dependency(
                    name=name,
                    version_spec=version_spec,
                    resolved_version=None,
                    dep_type=DependencyType.PRODUCTION,
                    extras=[],
                    source=path.name,
                    metadata=dep_meta,
                ))

        if (path.parent / "poetry.lock").is_file():
            poetry_lock = True

        return project_name, engine_constraints, deps, poetry_lock, raw_data

    def parse(self, path: Path) -> ProjectManifest:
        """Parse python manifest files."""
        path = path.resolve()
        req_path = path / "requirements.txt"
        toml_path = path / "pyproject.toml"
        pipfile_path = path / "Pipfile"

        project_name = path.name
        engine_constraints = {}
        dependencies = []
        metadata = {}
        manifest_files = []

        lockfile_present = False
        lockfile_path = None
        raw_toml_data: dict = {}

        if req_path.is_file():
            manifest_files.append(str(req_path))
            req_deps, req_meta = self._parse_requirements_txt(req_path)
            dependencies.extend(req_deps)
            if req_meta:
                metadata.update(req_meta)

        if toml_path.is_file():
            manifest_files.append(str(toml_path))
            toml_name, toml_engines, toml_deps, has_poetry_lock, raw_toml_data = self._parse_pyproject_toml(toml_path)

            if toml_name:
                project_name = toml_name
            if toml_engines:
                engine_constraints.update(toml_engines)

            dependencies.extend(toml_deps)

            if has_poetry_lock:
                lockfile_present = True
                lockfile_path = str(path / "poetry.lock")
                manifest_files.append(lockfile_path)

        if pipfile_path.is_file():
            manifest_files.append(str(pipfile_path))
            if (path / "Pipfile.lock").is_file():
                lockfile_present = True
                lockfile_path = str(path / "Pipfile.lock")
                manifest_files.append(lockfile_path)

        # Workspace detection
        is_workspace_root = False
        is_workspace_member = False
        workspace_root: Path | None = None
        workspace_members: list[Path] = []
        workspace_member_names: set[str] = set()

        if raw_toml_data:
            members, names = _extract_python_workspace_info(path, raw_toml_data)
            if members:
                is_workspace_root = True
                workspace_root = path
                workspace_members = members
                workspace_member_names = names | _get_python_member_names(members)

        if not is_workspace_root:
            ancestor_info = _find_python_workspace_root(path)
            if ancestor_info:
                is_workspace_member = True
                workspace_root, workspace_members = ancestor_info
                workspace_member_names = _get_python_member_names(workspace_members)
            else:
                # Check if any dependency is a sibling path dependency (e.g. path starts with ../)
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

        if lockfile_present and lockfile_path:
            direct_dep_names = {dep.name.lower() for dep in dependencies}
            resolved_map = {}
            lockfile_name = Path(lockfile_path).name

            if lockfile_name == "poetry.lock":
                try:
                    with open(lockfile_path, "rb") as f:
                        lock_data = tomllib.load(f)
                    if "package" in lock_data:
                        for pkg in lock_data["package"]:
                            name = pkg.get("name")
                            version = pkg.get("version")
                            if name and version:
                                resolved_map[name.lower()] = version
                except (tomllib.TOMLDecodeError, OSError):
                    pass
            elif lockfile_name == "Pipfile.lock":
                import json
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        lock_data = json.load(f)
                    for section in ["default", "develop"]:
                        if section in lock_data:
                            for name, details in lock_data[section].items():
                                version = details.get("version", "").lstrip("=")
                                if version:
                                    resolved_map[name.lower()] = version
                except (json.JSONDecodeError, OSError):
                    pass

            for dep in dependencies:
                if dep.name.lower() in resolved_map:
                    dep.resolved_version = resolved_map[dep.name.lower()]

            for pkg_name_lower, pkg_version in resolved_map.items():
                if pkg_name_lower not in direct_dep_names:
                    dependencies.append(
                        Dependency(
                            name=pkg_name_lower,
                            version_spec=pkg_version,
                            resolved_version=pkg_version,
                            dep_type=DependencyType.PRODUCTION,
                            extras=[],
                            source=lockfile_name,
                            metadata={"transitive": True}
                        )
                    )

        return ProjectManifest(
            project_path=path,
            project_name=project_name,
            ecosystem=self.ecosystem,
            dependencies=dependencies,
            engine_constraints=engine_constraints,
            lockfile_present=lockfile_present,
            lockfile_path=Path(lockfile_path) if lockfile_path else None,
            manifest_files=[Path(m) for m in manifest_files],
            metadata=metadata,
            workspace_root=workspace_root,
            workspace_members=workspace_members,
            is_workspace_root=is_workspace_root,
            is_workspace_member=is_workspace_member,
        )
