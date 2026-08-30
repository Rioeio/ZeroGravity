from __future__ import annotations

from pathlib import Path
from typing import Any

from zerogravity.parsers.base import (
    BaseParser,
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)


def _extract_go_workspace_info(path: Path, go_work_path: Path) -> tuple[list[Path], set[str]]:
    """Extract workspace member paths from a go.work file."""
    member_paths: set[Path] = set()
    member_names: set[str] = set()

    try:
        with open(go_work_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        in_use_block = False
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue

            comment_idx = line.find("//")
            if comment_idx >= 0:
                line = line[:comment_idx].strip()

            if line == "use (":
                in_use_block = True
                continue
            elif in_use_block and line == ")":
                in_use_block = False
                continue

            use_dir: str | None = None
            if in_use_block:
                use_dir = line.strip('"')
            elif line.startswith("use "):
                parts = line.split(None, 1)
                if len(parts) > 1:
                    use_dir = parts[1].strip().strip('"')

            if use_dir:
                clean_dir = use_dir.lstrip("./").strip("/")
                if not clean_dir:
                    candidate = path
                else:
                    candidate = (path / clean_dir).resolve()

                if candidate.is_dir() and (candidate / "go.mod").is_file() and candidate != path.resolve():
                    member_paths.add(candidate)
    except OSError:
        pass

    return sorted(list(member_paths)), member_names


def _find_go_workspace_root(path: Path) -> tuple[Path, list[Path]] | None:
    """Find ancestor directory that defines a go.work workspace containing this path."""
    current = path.resolve().parent
    while current != current.parent:
        go_work = current / "go.work"
        if go_work.is_file():
            members, _ = _extract_go_workspace_info(current, go_work)
            if path.resolve() in members:
                return current, members
        if (current / ".git").is_dir():
            break
        current = current.parent
    return None


def _get_go_member_modules(member_paths: list[Path]) -> set[str]:
    """Read module paths from member go.mod files."""
    modules: set[str] = set()
    for mp in member_paths:
        mod_file = mp / "go.mod"
        if mod_file.is_file():
            try:
                with open(mod_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("module "):
                            parts = line.split()
                            if len(parts) >= 2:
                                modules.add(parts[1].strip('"'))
                            break
            except OSError:
                pass
    return modules


class GoParser(BaseParser):
    """
    Parser for Go projects (go.mod and go.sum).
    """

    @property
    def ecosystem(self) -> Ecosystem:
        """Return the ecosystem for this parser."""
        return Ecosystem.GO

    def can_parse(self, path: Path) -> bool:
        """Check if go.mod or go.work exists in the directory."""
        return (path / "go.mod").is_file() or (path / "go.work").is_file()

    def _parse_go_sum(self, lockfile_path: Path) -> dict[str, str]:
        """
        Parse go.sum file and return a mapping of module_name -> latest resolved version.
        """
        resolved_map: dict[str, str] = {}
        try:
            with open(lockfile_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("//"):
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        mod_name = parts[0]
                        raw_ver = parts[1]
                        # Trim /go.mod suffix if present
                        version = raw_ver[:-7] if raw_ver.endswith("/go.mod") else raw_ver
                        # If not already present or if this is the non-/go.mod entry, store it
                        if mod_name not in resolved_map or not raw_ver.endswith("/go.mod"):
                            resolved_map[mod_name] = version
        except OSError:
            pass
        return resolved_map

    def parse(self, path: Path) -> ProjectManifest:
        """
        Parse go.mod and go.sum files into a ProjectManifest.
        """
        path = path.resolve()
        go_mod_path = path / "go.mod"

        if not go_mod_path.is_file():
            raise FileNotFoundError(f"go.mod not found in {path}")

        try:
            with open(go_mod_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            raise IOError(f"Could not read {go_mod_path}: {e}")

        project_name = path.name
        engine_constraints: dict[str, str] = {}
        metadata: dict[str, Any] = {}
        direct_deps: list[Dependency] = []
        indirect_mod_deps: list[Dependency] = []
        manifest_files: list[Path] = [go_mod_path]
        replace_map: dict[str, str] = {}

        in_block: str | None = None
        lines = content.splitlines()

        for line_num, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue

            has_indirect = "// indirect" in line

            comment_idx = line.find("//")
            clean_line = line[:comment_idx].strip() if comment_idx >= 0 else line

            # Check block closures
            if clean_line == ")":
                if in_block is None:
                    raise ValueError(f"Malformed go.mod in {go_mod_path}: unexpected ')' on line {line_num}")
                in_block = None
                continue

            # Check block openings
            if clean_line.endswith("(") and len(clean_line.split()) == 2 and clean_line.split()[1] == "(":
                block_name = clean_line.split()[0]
                if block_name in ("require", "replace", "exclude", "retract"):
                    in_block = block_name
                    continue
                else:
                    raise ValueError(f"Malformed go.mod in {go_mod_path}: unknown block '{block_name}' on line {line_num}")

            # Process block contents or single-line directives
            if in_block == "require":
                parts = clean_line.split()
                if len(parts) >= 2:
                    mod_name = parts[0].strip('"')
                    mod_ver = parts[1].strip('"')
                    meta: dict[str, Any] = {}
                    if has_indirect:
                        meta["indirect"] = True
                        meta["transitive"] = True
                        indirect_mod_deps.append(
                            Dependency(
                                name=mod_name,
                                version_spec=mod_ver,
                                resolved_version=mod_ver,
                                dep_type=DependencyType.PRODUCTION,
                                extras=[],
                                source="go.mod",
                                metadata=meta,
                            )
                        )
                    else:
                        direct_deps.append(
                            Dependency(
                                name=mod_name,
                                version_spec=mod_ver,
                                resolved_version=None,
                                dep_type=DependencyType.PRODUCTION,
                                extras=[],
                                source="go.mod",
                                metadata=meta,
                            )
                        )
                continue

            if in_block == "replace":
                if "=>" in clean_line:
                    left, right = clean_line.split("=>", 1)
                    old_mod = left.strip().split()[0].strip('"')
                    new_target = right.strip().strip('"')
                    replace_map[old_mod] = new_target
                continue

            if in_block in ("exclude", "retract"):
                continue

            # Single-line directives
            parts = clean_line.split()
            if not parts:
                continue

            directive = parts[0]

            if directive == "module":
                if len(parts) >= 2:
                    project_name = parts[1].strip('"')
                else:
                    raise ValueError(f"Malformed go.mod in {go_mod_path}: missing module name on line {line_num}")

            elif directive == "go":
                if len(parts) >= 2:
                    go_ver = parts[1].strip('"')
                    metadata["go_version"] = go_ver
                    engine_constraints["go"] = f">={go_ver}" if not go_ver.startswith((">=", ">", "=", "<")) else go_ver
                else:
                    raise ValueError(f"Malformed go.mod in {go_mod_path}: missing go version on line {line_num}")

            elif directive == "toolchain":
                if len(parts) >= 2:
                    metadata["toolchain"] = parts[1].strip('"')

            elif directive == "require":
                if len(parts) >= 3:
                    mod_name = parts[1].strip('"')
                    mod_ver = parts[2].strip('"')
                    meta = {}
                    if has_indirect:
                        meta["indirect"] = True
                        meta["transitive"] = True
                        indirect_mod_deps.append(
                            Dependency(
                                name=mod_name,
                                version_spec=mod_ver,
                                resolved_version=mod_ver,
                                dep_type=DependencyType.PRODUCTION,
                                extras=[],
                                source="go.mod",
                                metadata=meta,
                            )
                        )
                    else:
                        direct_deps.append(
                            Dependency(
                                name=mod_name,
                                version_spec=mod_ver,
                                resolved_version=None,
                                dep_type=DependencyType.PRODUCTION,
                                extras=[],
                                source="go.mod",
                                metadata=meta,
                            )
                        )

            elif directive == "replace":
                if "=>" in clean_line:
                    body = clean_line[len("replace"):].strip()
                    left, right = body.split("=>", 1)
                    old_mod = left.strip().split()[0].strip('"')
                    new_target = right.strip().strip('"')
                    replace_map[old_mod] = new_target

        if in_block is not None:
            raise ValueError(f"Malformed go.mod in {go_mod_path}: unclosed '{in_block}' block")

        # Apply replace mappings
        for dep in direct_deps + indirect_mod_deps:
            if dep.name in replace_map:
                replacement = replace_map[dep.name]
                dep.metadata["replace"] = replacement
                if replacement.startswith(".") or replacement.startswith("/"):
                    dep.metadata["path"] = replacement
                    dep.metadata["workspace_internal"] = True

        dependencies: list[Dependency] = list(direct_deps)

        # Workspace detection
        is_workspace_root = False
        is_workspace_member = False
        workspace_root: Path | None = None
        workspace_members: list[Path] = []
        workspace_member_names: set[str] = set()

        go_work_path = path / "go.work"
        if go_work_path.is_file():
            is_workspace_root = True
            workspace_root = path
            workspace_members, _ = _extract_go_workspace_info(path, go_work_path)
            workspace_member_names = _get_go_member_modules(workspace_members)
        else:
            ancestor_info = _find_go_workspace_root(path)
            if ancestor_info:
                is_workspace_member = True
                workspace_root, workspace_members = ancestor_info
                workspace_member_names = _get_go_member_modules(workspace_members)
            else:
                has_sibling_path_dep = any(
                    isinstance(d.metadata.get("path"), str) and d.metadata["path"].startswith("..")
                    for d in dependencies
                )
                if has_sibling_path_dep:
                    is_workspace_member = True
                    workspace_root = path.parent

        for dep in dependencies:
            if dep.name in workspace_member_names:
                dep.metadata["workspace_internal"] = True

        # Lockfile detection (go.sum)
        lockfile_present = False
        lockfile_path: Path | None = None

        if (path / "go.sum").is_file():
            lockfile_present = True
            lockfile_path = path / "go.sum"
        elif workspace_root and (workspace_root / "go.sum").is_file():
            lockfile_present = True
            lockfile_path = workspace_root / "go.sum"

        if lockfile_present and lockfile_path:
            manifest_files.append(lockfile_path)
            resolved_map = self._parse_go_sum(lockfile_path)

            direct_dep_names = {dep.name for dep in dependencies}

            for dep in dependencies:
                if dep.name in resolved_map:
                    dep.resolved_version = resolved_map[dep.name]

            excluded_names = direct_dep_names | workspace_member_names
            if project_name:
                excluded_names.add(project_name)

            # Include indirect dependencies from go.mod
            for ind_dep in indirect_mod_deps:
                if ind_dep.name in resolved_map:
                    ind_dep.resolved_version = resolved_map[ind_dep.name]
                if ind_dep.name not in excluded_names:
                    dependencies.append(ind_dep)
                    excluded_names.add(ind_dep.name)

            # Include remaining transitive dependencies from go.sum
            for mod_name, mod_version in resolved_map.items():
                if mod_name not in excluded_names:
                    excluded_names.add(mod_name)
                    dependencies.append(
                        Dependency(
                            name=mod_name,
                            version_spec=mod_version,
                            resolved_version=mod_version,
                            dep_type=DependencyType.PRODUCTION,
                            extras=[],
                            source="go.sum",
                            metadata={"transitive": True},
                        )
                    )
        else:
            # If no go.sum, still include indirect deps from go.mod if present
            direct_dep_names = {dep.name for dep in dependencies}
            for ind_dep in indirect_mod_deps:
                if ind_dep.name not in direct_dep_names:
                    dependencies.append(ind_dep)

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
