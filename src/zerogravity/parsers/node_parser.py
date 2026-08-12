from __future__ import annotations

import json
from pathlib import Path

from zerogravity.parsers.base import (
    BaseParser,
    Dependency,
    DependencyType,
    Ecosystem,
    ProjectManifest,
)


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
                import re
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        pattern = re.compile(r'^"?(@?[^@\n]+)@[^:\n]+"?:\n\s+version\s+"([^"]+)"', re.MULTILINE)
                        for match in pattern.finditer(content):
                            pkg_name = match.group(1)
                            pkg_version = match.group(2)
                            resolved_map[pkg_name] = pkg_version
                except OSError:
                    pass
            elif lockfile_name == "pnpm-lock.yaml":
                try:
                    with open(lockfile_path, "r", encoding="utf-8") as f:
                        in_packages = False
                        for line in f:
                            if line.startswith("packages:"):
                                in_packages = True
                                continue
                            if in_packages:
                                if not line.startswith("  "):
                                    in_packages = False
                                    continue
                                line = line.strip()
                                if line.startswith("'") or line.startswith("/"):
                                    clean_line = line.strip("':")
                                    if clean_line.startswith("/"):
                                        parts = clean_line[1:].split("/")
                                        if len(parts) >= 2:
                                            pkg_name = parts[0]
                                            pkg_version = parts[1]
                                            if pkg_name.startswith("@") and len(parts) >= 3:
                                                pkg_name = f"{parts[0]}/{parts[1]}"
                                                pkg_version = parts[2]
                                            pkg_version = pkg_version.split("(")[0].split("_")[0]
                                            resolved_map[pkg_name] = pkg_version
                except OSError:
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
            lockfile_path=lockfile_path,
            manifest_files=manifest_files,
            metadata=metadata
        )
