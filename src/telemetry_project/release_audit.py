"""Repository checks used to prepare a public release."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

MAX_FILE_BYTES = 5 * 1024 * 1024
REQUIRED_PUBLIC_FILES = (
    ".github/workflows/quality.yml",
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CITATION.cff",
    "pyproject.toml",
    "uv.lock",
    "docs/data-sources.md",
    "docs/release-checklist.md",
    "reports/model-report.md",
    "reports/release-audit.json",
    "reports/retrospective.md",
)
PROHIBITED_PATHS = ("AGENTS.md", ".project-local")
PROHIBITED_PREFIXES = (
    ".venv/",
    "artifacts/",
    "data/interim/",
    "data/processed/",
    "data/raw/",
    "logs/",
    "models/",
)
SECRET_PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
LOCAL_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


@dataclass(frozen=True)
class AuditCheck:
    """One release-audit result."""

    name: str
    passed: bool
    details: str


@dataclass(frozen=True)
class ReleaseAudit:
    """Machine-readable release-audit summary."""

    schema_version: int
    generated_at_utc: str
    candidate_files: int
    candidate_bytes: int
    largest_file: str
    largest_file_bytes: int
    passed: bool
    checks: tuple[AuditCheck, ...]


class ReleaseAuditError(RuntimeError):
    """Raised when the repository cannot be inspected."""


def _candidate_files(root: Path) -> tuple[Path, ...]:
    """Return tracked and unignored untracked files in the release candidate."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseAuditError("Unable to list the Git release candidate") from error
    return tuple(
        root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item
    )


def _check(name: str, failures: Sequence[str], success: str) -> AuditCheck:
    details = "; ".join(failures) if failures else success
    return AuditCheck(name=name, passed=not failures, details=details)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _check_required(root: Path) -> AuditCheck:
    missing = [name for name in REQUIRED_PUBLIC_FILES if not (root / name).is_file()]
    return _check("required public files", missing, "all required files are present")


def _check_paths(root: Path, files: Sequence[Path]) -> AuditCheck:
    failures: list[str] = []
    for path in files:
        relative = _relative(path, root)
        if relative in PROHIBITED_PATHS or relative.startswith(PROHIBITED_PREFIXES):
            failures.append(relative)
        if relative.startswith(".env") and relative != ".env.example":
            failures.append(relative)
    return _check(
        "tracked-content policy",
        sorted(set(failures)),
        "no private plans, secrets files, raw data, or generated model paths",
    )


def _check_sizes(root: Path, files: Sequence[Path], max_bytes: int) -> AuditCheck:
    failures = [
        f"{_relative(path, root)} ({path.stat().st_size} bytes)"
        for path in files
        if path.stat().st_size > max_bytes
    ]
    return _check(
        "oversized files",
        failures,
        f"no candidate file exceeds {max_bytes} bytes",
    )


def _check_text_content(
    root: Path, files: Sequence[Path]
) -> tuple[AuditCheck, AuditCheck]:
    secret_failures: list[str] = []
    path_failures: list[str] = []
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        relative = _relative(path, root)
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                secret_failures.append(f"{relative}: {label}")
        if any(pattern.search(text) for pattern in LOCAL_PATH_PATTERNS):
            path_failures.append(relative)
    return (
        _check(
            "secret patterns",
            secret_failures,
            "no high-confidence secret patterns found",
        ),
        _check("portable paths", path_failures, "no private absolute user paths found"),
    )


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    return unquote(target.split("#", maxsplit=1)[0])


def _check_links(root: Path, files: Sequence[Path]) -> AuditCheck:
    failures: list[str] = []
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        text = _read_text(path)
        if text is None:
            continue
        for match in MARKDOWN_LINK.finditer(text):
            target = _link_target(match.group(1))
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                failures.append(
                    f"{_relative(path, root)} -> {target} (outside repository)"
                )
                continue
            if not resolved.exists():
                failures.append(f"{_relative(path, root)} -> {target}")
    return _check("local Markdown links", failures, "all local Markdown links resolve")


def _check_notebooks(root: Path, files: Sequence[Path]) -> AuditCheck:
    failures: list[str] = []
    notebooks = [path for path in files if path.suffix.lower() == ".ipynb"]
    for path in notebooks:
        try:
            notebook = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            failures.append(f"{_relative(path, root)} ({type(error).__name__})")
            continue
        cells = notebook.get("cells", [])
        if any(
            cell.get("outputs") or cell.get("execution_count") is not None
            for cell in cells
        ):
            failures.append(_relative(path, root))
    success = (
        "no notebooks are published"
        if not notebooks
        else "notebook outputs are cleared"
    )
    return _check("notebook output", failures, success)


def _check_versions(root: Path) -> AuditCheck:
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package_text = (root / "src/telemetry_project/__init__.py").read_text(
            encoding="utf-8"
        )
        package_match = re.search(
            r'^__version__ = "([^"]+)"$', package_text, re.MULTILINE
        )
        project_version = str(project["project"]["version"])
        package_version = package_match.group(1) if package_match else "missing"
    except (KeyError, OSError, tomllib.TOMLDecodeError) as error:
        return AuditCheck("version metadata", False, type(error).__name__)
    failures = (
        []
        if project_version == package_version
        else [f"pyproject={project_version}, package={package_version}"]
    )
    return _check(
        "version metadata", failures, f"version {project_version} is consistent"
    )


def run_release_audit(
    root: Path,
    *,
    output: Path | None = None,
    max_file_bytes: int = MAX_FILE_BYTES,
    candidate_files: Sequence[Path] | None = None,
) -> ReleaseAudit:
    """Inspect the public release candidate and optionally save a JSON report."""
    root = root.resolve()
    files = (
        tuple(candidate_files)
        if candidate_files is not None
        else _candidate_files(root)
    )
    files = tuple(
        sorted((path.resolve() for path in files), key=lambda path: str(path))
    )
    missing_files = [path for path in files if not path.is_file()]
    if missing_files:
        raise ReleaseAuditError(f"Candidate file does not exist: {missing_files[0]}")

    text_checks = _check_text_content(root, files)
    checks = (
        _check_required(root),
        _check_paths(root, files),
        _check_sizes(root, files, max_file_bytes),
        *text_checks,
        _check_links(root, files),
        _check_notebooks(root, files),
        _check_versions(root),
    )
    sizes = [(path.stat().st_size, _relative(path, root)) for path in files]
    largest_bytes, largest_file = max(sizes, default=(0, ""))
    audit = ReleaseAudit(
        schema_version=1,
        generated_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        candidate_files=len(files),
        candidate_bytes=sum(size for size, _ in sizes),
        largest_file=largest_file,
        largest_file_bytes=largest_bytes,
        passed=all(check.passed for check in checks),
        checks=checks,
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(asdict(audit), indent=2) + "\n", encoding="utf-8")
    return audit
