from __future__ import annotations

import re

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from zerogravity.resolver.models import Severity


def is_semver(version_string: str) -> bool:
    """
    Returns True if the string looks like a semantic version
    (X.Y.Z with optional pre-release).
    """
    try:
        Version(version_string)
        return True
    except InvalidVersion:
        return False

def normalize_npm_specifier(spec: str) -> str:
    """
    Converts npm/node version range syntax to PEP 440 compatible specifiers.
    Handles ^, ~, exact pins, and simple ranges.
    """
    spec = spec.strip()
    if not spec or spec in ("*", "latest", "x", "X"):
        return "*"

    if "||" in spec:
        return " || ".join(normalize_npm_specifier(s.strip()) for s in spec.split("||"))

    # Handle 18.x, 18.X, 18.*, 18.*.*, ~18
    match = re.match(r"^(?:~)?(\d+)(?:\.[xX\*](?:\.[xX\*])?)?$", spec)
    if match:
        major = int(match.group(1))
        return f">={major}.0.0,<{major+1}.0.0"

    # For complex ranges with ||, take the union (check if version satisfies ANY).
    # Since PEP440 SpecifierSet doesn't support OR, we split and evaluate later,
    # but here we'll just parse the components or leave them for compare_version.
    # To keep this function purely string-based, we'll return the string as-is with replacements.

    def repl_caret(match: re.Match) -> str:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0
        if major == 0:
            if minor == 0:
                return f">={major}.{minor}.{patch},<0.0.{patch+1}"
            return f">={major}.{minor}.{patch},<0.{minor+1}.0"
        return f">={major}.{minor}.{patch},<{major+1}.0.0"

    def repl_tilde(match: re.Match) -> str:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0
        return f">={major}.{minor}.{patch},<{major}.{minor+1}.0"

    # Exact pin (e.g. 4.18.2)
    if re.match(r"^v?\d+\.\d+\.\d+$", spec):
        return f"=={spec.lstrip('v')}"

    # Replace ^ and ~
    spec = re.sub(r"\^(\d+)\.(\d+)\.(\d+)", repl_caret, spec)
    spec = re.sub(r"~(\d+)\.(\d+)\.(\d+)", repl_tilde, spec)

    return spec

def compare_version(required_spec: str, installed_version: str) -> Severity:
    """
    Compares an installed version against a required specifier.
    Uses packaging.version.Version and packaging.specifiers.SpecifierSet.
    """
    if required_spec in ("*", "latest"):
        return Severity.OK

    try:
        parsed_version = Version(installed_version)
    except InvalidVersion:
        return Severity.ERROR

    # Handle || union conditions
    specs = [s.strip() for s in required_spec.split("||")]

    matched_any = False
    is_newer = False
    valid_specifier_parsed = False

    for s in specs:
        norm_spec = normalize_npm_specifier(s)
        if norm_spec == "*":
            return Severity.OK

        try:
            spec_set = SpecifierSet(norm_spec)
            valid_specifier_parsed = True
            if parsed_version in spec_set:
                matched_any = True
                break

            # Check if installed is newer (satisfies lower bounds but violates upper)
            lower_bounds = ",".join(b for b in norm_spec.split(",") if not b.startswith("<") and not b.startswith("!="))
            if lower_bounds:
                lower_set = SpecifierSet(lower_bounds)
                if parsed_version in lower_set:
                    is_newer = True
        except Exception:
            continue

    if not valid_specifier_parsed:
        return Severity.INFO

    if matched_any:
        return Severity.OK
    elif is_newer:
        return Severity.WARNING
    else:
        return Severity.ERROR
