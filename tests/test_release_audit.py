"""Tests for public release-candidate auditing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from telemetry_project.release_audit import (
    MAX_FILE_BYTES,
    REQUIRED_PUBLIC_FILES,
    ReleaseAuditError,
    _candidate_files,
    run_release_audit,
)


def _write(path: Path, content: str = "release file\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _valid_candidate(root: Path) -> list[Path]:
    files = [_write(root / name) for name in REQUIRED_PUBLIC_FILES]
    _write(
        root / "pyproject.toml",
        '[project]\nname = "telemetry-project"\nversion = "1.0.0"\n',
    )
    files.append(
        _write(
            root / "src/telemetry_project/__init__.py",
            '__version__ = "1.0.0"\n',
        )
    )
    return sorted(set(files))


def _failed_checks(root: Path, files: list[Path]) -> set[str]:
    audit = run_release_audit(root, candidate_files=files)
    return {check.name for check in audit.checks if not check.passed}


def test_release_audit_passes_and_writes_machine_readable_record(
    tmp_path: Path,
) -> None:
    files = _valid_candidate(tmp_path)
    _write(tmp_path / "docs/guide.md", "See [results](../reports/model-report.md).\n")
    files.append(tmp_path / "docs/guide.md")
    output = tmp_path / "reports/release-audit.json"

    audit = run_release_audit(tmp_path, output=output, candidate_files=files)

    assert audit.passed is True
    assert audit.candidate_files == len(files)
    assert audit.candidate_bytes > 0
    assert audit.largest_file
    assert all(check.passed for check in audit.checks)
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True


def test_release_audit_detects_publication_risks(tmp_path: Path) -> None:
    files = _valid_candidate(tmp_path)
    files.extend(
        [
            _write(tmp_path / "data/raw/session.json", "raw\n"),
            _write(tmp_path / ".env", "TOKEN=value\n"),
            _write(
                tmp_path / "notes.md", "[missing](missing.md)\nC:\\Users\\name\\x\n"
            ),
            _write(
                tmp_path / "token.txt",
                "ghp_" + "abcdefghijklmnopqrstuvwxyz123456\n",
            ),
            _write(tmp_path / "large.bin", "x" * 11),
            _write(
                tmp_path / "analysis.ipynb",
                json.dumps(
                    {"cells": [{"execution_count": 1, "outputs": [{"text": "x"}]}]}
                ),
            ),
        ]
    )

    failed = _failed_checks(tmp_path, files)
    size_audit = run_release_audit(tmp_path, candidate_files=files, max_file_bytes=10)

    assert {
        "tracked-content policy",
        "secret patterns",
        "portable paths",
        "local Markdown links",
        "notebook output",
    } <= failed
    assert "oversized files" in {
        check.name for check in size_audit.checks if not check.passed
    }


def test_release_audit_handles_external_links_and_cleared_notebook(
    tmp_path: Path,
) -> None:
    files = _valid_candidate(tmp_path)
    files.extend(
        [
            _write(
                tmp_path / "links.md",
                "[web](https://example.com) [mail](mailto:a@example.com) "
                '[anchor](#section) [readme](<README.md#setup> "title")\n',
            ),
            _write(
                tmp_path / "clean.ipynb",
                json.dumps({"cells": [{"execution_count": None, "outputs": []}]}),
            ),
            _write(tmp_path / "image.png", "not\x00text"),
        ]
    )

    assert run_release_audit(tmp_path, candidate_files=files).passed is True


def test_release_audit_reports_bad_notebook_and_version_metadata(
    tmp_path: Path,
) -> None:
    files = _valid_candidate(tmp_path)
    files.append(_write(tmp_path / "broken.ipynb", "not json"))
    _write(
        tmp_path / "src/telemetry_project/__init__.py",
        '__version__ = "2.0.0"\n',
    )

    assert {"notebook output", "version metadata"} <= _failed_checks(tmp_path, files)


def test_release_audit_reports_invalid_project_metadata(tmp_path: Path) -> None:
    files = _valid_candidate(tmp_path)
    _write(tmp_path / "pyproject.toml", "not = [valid\n")

    assert "version metadata" in _failed_checks(tmp_path, files)


def test_release_audit_rejects_missing_candidate_file(tmp_path: Path) -> None:
    with pytest.raises(ReleaseAuditError, match="does not exist"):
        run_release_audit(tmp_path, candidate_files=[tmp_path / "missing"])


def test_candidate_files_reads_null_delimited_git_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = Mock(stdout=b"README.md\0docs/guide.md\0")
    monkeypatch.setattr(
        "telemetry_project.release_audit.subprocess.run", Mock(return_value=result)
    )

    assert _candidate_files(tmp_path) == (
        tmp_path / "README.md",
        tmp_path / "docs/guide.md",
    )


@pytest.mark.parametrize(
    "error",
    [OSError("missing git"), subprocess.CalledProcessError(1, ["git"])],
)
def test_candidate_files_wraps_git_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(
        "telemetry_project.release_audit.subprocess.run", Mock(side_effect=error)
    )

    with pytest.raises(ReleaseAuditError, match="Unable to list"):
        _candidate_files(tmp_path)


def test_default_file_limit_is_five_mebibytes() -> None:
    assert MAX_FILE_BYTES == 5 * 1024 * 1024
