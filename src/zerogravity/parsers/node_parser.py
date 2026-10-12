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


def _clean_jsonc(content: str) -> str:
    """Tolerantly strip comments and trailing commas from JSONC content."""
    pattern = r'("(?:\\.|[^"\\])*")|//[^\r\n]*|/\*[\s\S]*?\*/'

    def _repl(m: re.Match) -> str:
        return m.group(1) if m.group(1) is not None else ""

    cleaned = re.sub(pattern, _repl, content)
    return re.sub(r',\s*([\]}])', r'\1', cleaned)


def _parse_yarn_berry_selector(selector: str) -> tuple[str, bool]:
    """Derive package name and whether it is workspace-internal from Yarn Berry selector."""
    sel = selector.strip().strip('"').strip("'")
    if "@workspace:" in sel:
        return sel.split("@workspace:")[0], True
    if "@npm:" in sel:
        return sel.split("@npm:")[0], False
    if "@patch:" in sel:
        return sel.split("@patch:")[0], False
    if "@git:" in sel:
        return sel.split("@git:")[0], False
    at_idx = sel.rfind("@")
    if at_idx > 0:
        return sel[:at_idx], False
    return sel, False


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

        candidate_locks = [
            "package-lock.json",
            "npm-shrinkwrap.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "bun.lock",
            "bun.lockb",
        ]
        for lock_name in candidate_locks:
            lp = path / lock_name
            if lp.is_file():
                lockfile_present = True
                lockfile_path = str(lp)
                lockfile_name = lock_name
                manifest_files.append(str(lp))
                break

        if lockfile_name == "bun.lockb":
            metadata["bun_lockb_present"] = True

        if lockfile_path and lockfile_name:
            resolved_map: dict[str, str] = {}
            workspace_internal_pkgs: set[str] = set()
            direct_dep_names = {dep.name for dep in dependencies}

            if lockfile_name in ("package-lock.json", "npm-shrinkwrap.json"):
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        lock_data = json.load(f)

                    if "packages" in lock_data:
                        for k, v in lock_data["packages"].items():
                            if k.startswith("node_modules/"):
                                pkg_name = k.split("node_modules/")[-1]
                                ver = v.get("version")
                                if ver:
                                    resolved_map[pkg_name] = str(ver)

                    if "dependencies" in lock_data:
                        def _collect_v1(deps: dict) -> None:
                            for name, info in deps.items():
                                if isinstance(info, dict):
                                    ver = info.get("version")
                                    if ver and name not in resolved_map:
                                        resolved_map[name] = str(ver)
                                    if "dependencies" in info and isinstance(info["dependencies"], dict):
                                        _collect_v1(info["dependencies"])
                        _collect_v1(lock_data["dependencies"])
                except (json.JSONDecodeError, OSError):
                    pass
            elif lockfile_name == "yarn.lock":
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    if "__metadata:" in content:
                        berry_data = yaml.safe_load(content) or {}
                        if isinstance(berry_data, dict):
                            for key, val in berry_data.items():
                                if key == "__metadata" or not isinstance(val, dict):
                                    continue
                                ver = val.get("version")
                                if ver is not None:
                                    for part in str(key).split(","):
                                        pkg_name, is_ws = _parse_yarn_berry_selector(part)
                                        if pkg_name:
                                            resolved_map[pkg_name] = str(ver)
                                            if is_ws:
                                                workspace_internal_pkgs.add(pkg_name)
                    else:
                        for match in _YARN_ENTRY_RE.finditer(content):
                            selectors_blob, pkg_version = match.group(1), match.group(2)
                            first_selector = selectors_blob.split(",")[0]
                            pkg_name = _yarn_selector_name(first_selector)
                            if pkg_name:
                                resolved_map[pkg_name] = pkg_version
                except (OSError, yaml.YAMLError):
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
            elif lockfile_name == "bun.lock":
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    data = json.loads(_clean_jsonc(content))
                    pkgs = data.get("packages", {})
                    if isinstance(pkgs, dict):
                        for k, v in pkgs.items():
                            if isinstance(v, list) and v:
                                item = str(v[0])
                                at_idx = item.rfind("@")
                                if at_idx > 0:
                                    resolved_map[item[:at_idx]] = item[at_idx + 1:]
                                else:
                                    at_idx2 = k.rfind("@")
                                    if at_idx2 > 0:
                                        resolved_map[k[:at_idx2]] = k[at_idx2 + 1:]
                            elif isinstance(v, dict):
                                ver = v.get("version")
                                at_idx = k.rfind("@")
                                pkg_name = k[:at_idx] if at_idx > 0 else k
                                if ver:
                                    resolved_map[pkg_name] = str(ver)
                            elif isinstance(v, str):
                                at_idx = v.rfind("@")
                                if at_idx > 0:
                                    resolved_map[v[:at_idx]] = v[at_idx + 1:]
                                else:
                                    at_idx2 = k.rfind("@")
                                    pkg_name = k[:at_idx2] if at_idx2 > 0 else k
                                    resolved_map[pkg_name] = v
                except (json.JSONDecodeError, OSError):
                    pass

            if lockfile_name != "bun.lockb" and len(resolved_map) == 0:
                metadata["lockfile_zero_resolved"] = True

            for dep in dependencies:
                if dep.name in resolved_map:
                    dep.resolved_version = resolved_map[dep.name]
                if dep.name in workspace_internal_pkgs:
                    dep.metadata["workspace_internal"] = True

            for pkg_name, pkg_version in resolved_map.items():
                if pkg_version and pkg_name not in direct_dep_names:
                    meta: dict = {"transitive": True}
                    if pkg_name in workspace_internal_pkgs:
                        meta["workspace_internal"] = True
                    dependencies.append(
                        Dependency(
                            name=pkg_name,
                            version_spec=pkg_version,
                            resolved_version=pkg_version,
                            dep_type=DependencyType.PRODUCTION,
                            extras=[],
                            source=lockfile_name,
                            metadata=meta,
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
