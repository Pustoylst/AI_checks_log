from pathlib import Path

import pytest

from app.fixes import apply_approved_fix


def test_fix_requires_approval(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("TIMEOUT = 60\n", encoding="utf-8")

    with pytest.raises(PermissionError):
        apply_approved_fix(tmp_path, "service.py", "TIMEOUT = 60", "TIMEOUT = 120", False)


def test_fix_creates_backup_and_replaces_exact_text(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("TIMEOUT = 60\n", encoding="utf-8")

    path, backup_path = apply_approved_fix(tmp_path, "service.py", "TIMEOUT = 60", "TIMEOUT = 120", True)

    assert path == "service.py"
    assert Path(backup_path).read_text(encoding="utf-8") == "TIMEOUT = 60\n"
    assert (tmp_path / "service.py").read_text(encoding="utf-8") == "TIMEOUT = 120\n"


def test_fix_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        apply_approved_fix(tmp_path, "../../etc/passwd", "root", "changed", True)