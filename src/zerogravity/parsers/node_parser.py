from __future__ import annotations

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
        Check if package.json exists in the directory.
        """
        return (path / "package.json").is_file()

    def parse(self, path: Path) -> ProjectManifest:
        """
        Parse package.json and associated lockfiles.
        """
        package_json_path = path / "package.json"

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
        metadata = {}
        if "workspaces" in data:
            metadata["workspaces"] = data["workspaces"]

        manifest_files = [str(package_json_path)]

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
            metadata=metadata
        )
