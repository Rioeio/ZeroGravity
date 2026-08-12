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
        
        for lock_name in ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"]:
            lp = path / lock_name
            if lp.is_file():
                lockfile_present = True
                lockfile_path = str(lp)
                manifest_files.append(str(lp))
                break
                
        # Parse package-lock.json for resolved versions
        if lockfile_path and lockfile_path.endswith("package-lock.json"):
            try:
                with open(lockfile_path, "r", encoding="utf-8") as f:
                    lock_data = json.load(f)
                
                # Check for v2/v3 format (packages) or v1 (dependencies)
                resolved_map = {}
                if "packages" in lock_data:
                    for k, v in lock_data["packages"].items():
                        if k.startswith("node_modules/"):
                            pkg_name = k[len("node_modules/"):]
                            resolved_map[pkg_name] = v.get("version")
                elif "dependencies" in lock_data:
                    for k, v in lock_data["dependencies"].items():
                        resolved_map[k] = v.get("version")
                        
                for dep in dependencies:
                    if dep.name in resolved_map:
                        dep.resolved_version = resolved_map[dep.name]
            except (json.JSONDecodeError, OSError):
                pass # Ignore lockfile parsing errors

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
