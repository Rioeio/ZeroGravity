from __future__ import annotations

from pathlib import Path

from zerogravity.parsers.node_parser import NodeParser
from zerogravity.resolver.conflict_detector import _check_lockfiles
from zerogravity.resolver.models import Severity


def test_yarn_berry_resolution(tmp_path: Path):
    """Yarn Berry (__metadata:) resolves lodash and transitive @babel/core."""
    package_json = """{
  "name": "berry-app",
  "dependencies": {
    "lodash": "^4.17.21"
  }
}"""
    yarn_lock = """__metadata:
  version: 6
  cacheKey: 8

"@babel/core@npm:^7.0.0, @babel/core@npm:^7.12.3":
  version: 7.20.0
  resolution: "@babel/core@npm:7.20.0"

"lodash@npm:^4.17.21":
  version: 4.17.21
  resolution: "lodash@npm:4.17.21"
"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "yarn.lock").write_text(yarn_lock, encoding="utf-8")

    manifest = NodeParser().parse(tmp_path)
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path is not None
    assert manifest.lockfile_path.name == "yarn.lock"

    # lodash resolved to 4.17.21
    lodash_dep = next((d for d in manifest.dependencies if d.name == "lodash"), None)
    assert lodash_dep is not None
    assert lodash_dep.resolved_version == "4.17.21"

    # @babel/core transitive dependency resolved to 7.20.0
    babel_dep = next((d for d in manifest.dependencies if d.name == "@babel/core"), None)
    assert babel_dep is not None
    assert babel_dep.resolved_version == "7.20.0"
    assert babel_dep.metadata.get("transitive") is True


def test_yarn_berry_workspace(tmp_path: Path):
    """Yarn Berry workspace: entries are flagged as workspace_internal."""
    package_json = """{
  "name": "root-app",
  "dependencies": {
    "my-pkg": "workspace:packages/my-pkg"
  }
}"""
    yarn_lock = """__metadata:
  version: 6

"my-pkg@workspace:packages/my-pkg":
  version: 1.0.0
  resolution: "my-pkg@workspace:packages/my-pkg"
"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "yarn.lock").write_text(yarn_lock, encoding="utf-8")

    manifest = NodeParser().parse(tmp_path)
    pkg_dep = next((d for d in manifest.dependencies if d.name == "my-pkg"), None)
    assert pkg_dep is not None
    assert pkg_dep.metadata.get("workspace_internal") is True


def test_bun_lock_jsonc(tmp_path: Path):
    """bun.lock JSONC text format parses packages map correctly."""
    package_json = """{
  "name": "bun-app",
  "dependencies": {
    "react": "^19.0.0"
  }
}"""
    bun_lock = """// Bun lockfile v1
{
  "lockfileVersion": 1,
  "workspaces": {
    "": {
      "name": "bun-app",
      "dependencies": {
        "react": "^19.0.0",
      },
    },
  },
  "packages": {
    "react@19.0.0": ["react@19.0.0", "", {}, "sha512-mock"],
    "clsx@2.1.1": ["clsx@2.1.1", "", {}, "sha512-mock"],
  },
}
"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "bun.lock").write_text(bun_lock, encoding="utf-8")

    manifest = NodeParser().parse(tmp_path)
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path is not None
    assert manifest.lockfile_path.name == "bun.lock"

    react_dep = next((d for d in manifest.dependencies if d.name == "react"), None)
    assert react_dep is not None
    assert react_dep.resolved_version == "19.0.0"

    clsx_dep = next((d for d in manifest.dependencies if d.name == "clsx"), None)
    assert clsx_dep is not None
    assert clsx_dep.resolved_version == "2.1.1"
    assert clsx_dep.metadata.get("transitive") is True


def test_bun_lockb_binary_issue(tmp_path: Path):
    """Binary bun.lockb emits an INFO issue advising upgrade to Bun 1.2+."""
    package_json = """{
  "name": "bun-old-app",
  "dependencies": {
    "react": "^18.0.0"
  }
}"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "bun.lockb").write_bytes(b"\x00bun\x00lockb\x00binary\x00data")

    manifest = NodeParser().parse(tmp_path)
    issues = _check_lockfiles(manifest)

    info_issues = [i for i in issues if i.severity == Severity.INFO]
    assert any("not parsed: upgrade to Bun 1.2+ or run bun install --save-text-lockfile" in i.message for i in info_issues)


def test_package_lock_v1_nested_tree(tmp_path: Path):
    """package-lock.json lockfileVersion 1 parses nested dependencies tree."""
    package_json = """{
  "name": "v1-app",
  "dependencies": {
    "express": "^4.18.2"
  }
}"""
    package_lock_v1 = """{
  "name": "v1-app",
  "version": "1.0.0",
  "lockfileVersion": 1,
  "requires": true,
  "dependencies": {
    "express": {
      "version": "4.18.2",
      "requires": {
        "accepts": "~1.3.8"
      },
      "dependencies": {
        "accepts": {
          "version": "1.3.8"
        }
      }
    }
  }
}"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(package_lock_v1, encoding="utf-8")

    manifest = NodeParser().parse(tmp_path)
    assert manifest.lockfile_present is True

    express_dep = next((d for d in manifest.dependencies if d.name == "express"), None)
    assert express_dep is not None
    assert express_dep.resolved_version == "4.18.2"

    accepts_dep = next((d for d in manifest.dependencies if d.name == "accepts"), None)
    assert accepts_dep is not None
    assert accepts_dep.resolved_version == "1.3.8"
    assert accepts_dep.metadata.get("transitive") is True


def test_npm_shrinkwrap(tmp_path: Path):
    """npm-shrinkwrap.json is recognized and parsed like package-lock.json."""
    package_json = """{
  "name": "shrinkwrap-app",
  "dependencies": {
    "lodash": "^4.17.21"
  }
}"""
    shrinkwrap = """{
  "name": "shrinkwrap-app",
  "version": "1.0.0",
  "lockfileVersion": 2,
  "packages": {
    "": {
      "name": "shrinkwrap-app"
    },
    "node_modules/lodash": {
      "version": "4.17.21"
    }
  }
}"""
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "npm-shrinkwrap.json").write_text(shrinkwrap, encoding="utf-8")

    manifest = NodeParser().parse(tmp_path)
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path is not None
    assert manifest.lockfile_path.name == "npm-shrinkwrap.json"

    lodash_dep = next((d for d in manifest.dependencies if d.name == "lodash"), None)
    assert lodash_dep is not None
    assert lodash_dep.resolved_version == "4.17.21"


def test_zero_resolved_warning(tmp_path: Path):
    """A present lockfile that yields zero resolved packages emits a visible warning."""
    package_json = """{
  "name": "broken-lock-app",
  "dependencies": {
    "lodash": "^4.17.21"
  }
}"""
    # Yarn lock with unparseable or empty contents
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("# empty lockfile\n", encoding="utf-8")

    manifest = NodeParser().parse(tmp_path)
    assert manifest.lockfile_present is True

    issues = _check_lockfiles(manifest)
    warn_issues = [i for i in issues if i.severity == Severity.WARNING]
    assert len(warn_issues) > 0
    assert any("zero resolved" in i.message.lower() for i in warn_issues)
