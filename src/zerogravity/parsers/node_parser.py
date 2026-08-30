import fnmatch
import json
import re
from pathlib import Path

import yaml

from zerogravity.parsers.base import (
    BaseParser,
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)

_YARN_ENTRY_RE = re.compile(
    r'^((?:"[^"]+"|[^\s,]+)(?:,\s*(?:"[^"]+"|[^\s,]+))*):\n\s+version\s+"([^"]+)"',
    re.MULTILINE,
)


def _yarn_selector_name(selector: str) -> str:
    """Extract the package name from one yarn.lock selector ('name@range')."""
    selector = selector.strip().strip('"')
    at_idx = selector.rfind("@")
    if selector.startswith("@"):
        # scoped package: keep the scope, split before the range's own '@'
        return selector[:at_idx] if at_idx > 0 else selector
    return selector[:at_idx] if at_idx > 0 else selector


def _parse_pnpm_package_key(key: str) -> tuple[str, str] | None:
    """
    Parse a pnpm-lock.yaml `packages` section key into (name, version).

    pnpm has changed this key format across major versions:
      v9+ (current, both pnpm 9/10/11):  'name@1.2.3'  /  '@scope/name@1.2.3'
      v6:                                 /name@1.2.3
      pre-v6:                             /name/1.2.3  /  /@scope/name/1.2.3
                                           (sometimes with a peer-doppelganger
                                           suffix: /@scope/name/1.2.3_@peer@1.0.0)

    Tries whichever separator ('/' or '@') is actually followed by something
    version-shaped, since a scoped name's own '/' and '@' would otherwise be
    ambiguous with the real separator. Peer-dependency suffixes ('(peer@1.0.0)'
    or legacy '_hash') are stripped from the extracted version.
    """
    core = str(key).lstrip("/").split("(", 1)[0]
    if not core:
        return None

    def _looks_like_version(s: str) -> bool:
        return bool(s) and s[0].isdigit()

    last_slash = core.rfind("/")
    if last_slash > 0 and _looks_like_version(core[last_slash + 1:]):
        name, version = core[:last_slash], core[last_slash + 1:]
    else:
        at_idx = core.rfind("@")
        if at_idx > 0 and _looks_like_version(core[at_idx + 1:]):
            name, version = core[:at_idx], core[at_idx + 1:]
        elif last_slash > 0:
            name, version = core[:last_slash], core[last_slash + 1:]
        else:
            return None

    version = version.split("_")[0].strip()
    name = name.strip()
    if not name or not version or not version[0].isdigit():
        return None
    return name, version


def _extract_node_workspace_patterns(package_json_data: dict, path: Path) -> list[str]:
    """Extract workspace glob patterns from package.json and/or pnpm-workspace.yaml."""
    patterns: list[str] = []
    if "workspaces" in package_json_data:
        ws = package_json_data["workspaces"]
        if isinstance(ws, list):
            patterns.extend(ws)
        elif isinstance(ws, dict) and "packages" in ws and isinstance(ws["packages"], list):
            patterns.extend(ws["packages"])

    pnpm_ws = path / "pnpm-workspace.yaml"
    if pnpm_ws.is_file():
        try:
            with open(pnpm_ws, "r", encoding="utf-8") as f:
                pdata = yaml.safe_load(f) or {}
                if isinstance(pdata, dict) and "packages" in pdata and isinstance(pdata["packages"], list):
                    patterns.extend(pdata["packages"])
        except Exception:
            pass

    return patterns


def _resolve_node_workspace_members(root_path: Path, patterns: list[str]) -> list[Path]:
    """Expand workspace glob patterns to find member directories."""
    inclusion_patterns = [p for p in patterns if not p.startswith("!")]
    exclusion_patterns = [p[1:] for p in patterns if p.startswith("!")]

    members: set[Path] = set()
    for pat in inclusion_patterns:
        clean_pat = pat.lstrip("./").strip("/")
        if not clean_pat:
            continue
        try:
            for p in root_path.glob(clean_pat):
                if p.is_dir() and (p / "package.json").is_file() and p.resolve() != root_path.resolve():
                    rel = p.relative_to(root_path).as_posix()
                    excluded = False
                    for expat in exclusion_patterns:
                        clean_expat = expat.lstrip("./").strip("/")
                        if fnmatch.fnmatch(rel, clean_expat) or fnmatch.fnmatch(p.name, clean_expat):
                            excluded = True
                            break
                    if not excluded:
                        members.add(p.resolve())
        except Exception:
            pass

    return sorted(list(members))


def _find_node_workspace_root(path: Path) -> tuple[Path, list[Path]] | None:
    """Find ancestor directory that defines a workspace containing this path."""
    current = path.resolve().parent
    while current != current.parent:
        pkg_json = current / "package.json"
        pnpm_ws = current / "pnpm-workspace.yaml"
        if pkg_json.is_file() or pnpm_ws.is_file():
            patterns: list[str] = []
            if pkg_json.is_file():
                try:
                    with open(pkg_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    patterns.extend(_extract_node_workspace_patterns(data, current))
                except Exception:
                    pass
            if pnpm_ws.is_file() and not patterns:
                patterns.extend(_extract_node_workspace_patterns({}, current))

            if patterns:
                members = _resolve_node_workspace_members(current, patterns)
                if path.resolve() in members:
                    return current, members
        if (current / ".git").is_dir():
            break
        current = current.parent
    return None


def _get_workspace_member_names(member_paths: list[Path]) -> set[str]:
    """Read package names for workspace members."""
    names: set[str] = set()
    for mp in member_paths:
        pkg_file = mp / "package.json"
        if pkg_file.is_file():
            try:
                with open(pkg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "name" in data and isinstance(data["name"], str):
                    names.add(data["name"])
            except Exception:
                pass
    return names


class NodeParser(BaseParser):
    """
    Parser for Node.js projects (package.json and lockfiles).
    """

    @property
    def ecosystem(self) -> Ecosystem:
        """Return the ecosystem for this parser."""
        return Ecosystem.NODE

    def can_parse(self, path: Path) -> bool:
        """
        Check if package.json or pnpm-workspace.yaml exists in the directory.
        """
        return (path / "package.json").is_file() or (path / "pnpm-workspace.yaml").is_file()

    def parse(self, path: Path) -> ProjectManifest:
        """
        Parse package.json and associated lockfiles.
        """
        path = path.resolve()
        package_json_path = path / "package.json"
        data: dict = {}

        if package_json_path.is_file():
            try:
                with open(package_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed JSON in {package_json_path}: {e}")
            except OSError as e:
                raise IOError(f"Could not read {package_json_path}: {e}")

        project_name = data.get("name", path.name)
        dependencies: list[Dependency] = []

        # Parse dependencies
        dep_sections = {
            "dependencies": DependencyType.PRODUCTION,
            "devDependencies": DependencyType.DEVELOPMENT,
            "peerDependencies": DependencyType.PEER,
            "optionalDependencies": DependencyType.OPTIONAL,
        }

        for section, dep_type in dep_sections.items():
            if section in data and isinstance(data[section], dict):
                for name, version_spec in data[section].items():
                    dependencies.append(
                        Dependency(
                            name=name,
                            version_spec=version_spec,
                            resolved_version=None,
                            dep_type=dep_type,
                            extras=[],
                            source="package.json",
                            metadata={}
                        )
                    )

        engine_constraints = data.get("engines", {})
        metadata: dict = {}

        # Workspace detection
        workspace_patterns = _extract_node_workspace_patterns(data, path)
        is_workspace_root = False
        is_workspace_member = False
        workspace_root: Path | None = None
        workspace_members: list[Path] = []
        workspace_member_names: set[str] = set()

        if workspace_patterns:
            is_workspace_root = True
            workspace_root = path
            workspace_members = _resolve_node_workspace_members(path, workspace_patterns)
            metadata["workspaces"] = workspace_patterns
            workspace_member_names = _get_workspace_member_names(workspace_members)
        else:
            ancestor_info = _find_node_workspace_root(path)
            if ancestor_info:
                is_workspace_member = True
                workspace_root, workspace_members = ancestor_info
                workspace_member_names = _get_workspace_member_names(workspace_members)

        # Flag workspace-internal dependencies
        for dep in dependencies:
            if (
                dep.name in workspace_member_names
                or dep.version_spec.startswith("workspace:")
                or dep.version_spec.startswith("file:")
            ):
                dep.metadata["workspace_internal"] = True

        manifest_files = [str(package_json_path)] if package_json_path.is_file() else []
        pnpm_ws_path = path / "pnpm-workspace.yaml"
        if pnpm_ws_path.is_file():
            manifest_files.append(str(pnpm_ws_path))

        # Detect lockfiles
        lockfile_present = False
        lockfile_path = None
        lockfile_name = None

        for lock_name in ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"]:
            lp = path / lock_name
            if lp.is_file():
                lockfile_present = True
                lockfile_path = str(lp)
                lockfile_name = lock_name
                manifest_files.append(str(lp))
                break

        if lockfile_path and lockfile_name:
            resolved_map = {}
            direct_dep_names = {dep.name for dep in dependencies}

            if lockfile_name == "package-lock.json":
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        lock_data = json.load(f)

                    if "packages" in lock_data:
                        for k, v in lock_data["packages"].items():
                            if k.startswith("node_modules/"):
                                pkg_name = k[len("node_modules/"):]
                                resolved_map[pkg_name] = v.get("version")
                            elif k == "" and "dependencies" in v:
                                pass
                    elif "dependencies" in lock_data:
                        for k, v in lock_data["dependencies"].items():
                            resolved_map[k] = v.get("version")
                except (json.JSONDecodeError, OSError):
                    pass
            elif lockfile_name == "yarn.lock":
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    for match in _YARN_ENTRY_RE.finditer(content):
                        selectors_blob, pkg_version = match.group(1), match.group(2)
                        first_selector = selectors_blob.split(",")[0]
                        pkg_name = _yarn_selector_name(first_selector)
                        if pkg_name:
                            resolved_map[pkg_name] = pkg_version
                except OSError:
                    pass
            elif lockfile_name == "pnpm-lock.yaml":
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        lock_data = yaml.safe_load(f) or {}
                    for key in (lock_data.get("packages") or {}):
                        parsed = _parse_pnpm_package_key(key)
                        if parsed:
                            pkg_name, pkg_version = parsed
                            resolved_map[pkg_name] = pkg_version
                except (OSError, yaml.YAMLError):
                    pass

            for dep in dependencies:
                if dep.name in resolved_map:
                    dep.resolved_version = resolved_map[dep.name]

            for pkg_name, pkg_version in resolved_map.items():
                if pkg_version and pkg_name not in direct_dep_names:
                    dependencies.append(
                        Dependency(
                            name=pkg_name,
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
