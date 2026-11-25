from pathlib import Path

import pytest

from app.fixes import apply_approved_fix


def test_fix_requires_approval(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("TIMEOUT = 60\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        apply_approved_fix(tmp_path, "service.py", "TIMEOUT = 60", "TIMEOUT = 120", False)
    assert source.read_text(encoding="utf-8") == "TIMEOUT = 60\n"
    assert list(tmp_path.iterdir()) == [source]


def test_fix_replaces_exact_text_without_creating_files(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("TIMEOUT = 60\n", encoding="utf-8")
    path = apply_approved_fix(tmp_path, "service.py", "TIMEOUT = 60", "TIMEOUT = 120", True)
    assert path == "service.py"
    assert source.read_text(encoding="utf-8") == "TIMEOUT = 120\n"
    apply_approved_fix(tmp_path, "service.py", "120", "180", True)
    assert source.read_text(encoding="utf-8") == "TIMEOUT = 180\n"
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("original, old, new", [
    ("old\n", "missing", "new"),
    ("old old\n", "old", "new"),
    ("old\n", "old", "old"),
    ("old\n", "", "new"),
])
def test_invalid_fix_leaves_source_and_directory_unchanged(tmp_path, original, old, new):
    source = tmp_path / "service.py"
    source.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        apply_approved_fix(tmp_path, "service.py", old, new, True)
    assert source.read_text(encoding="utf-8") == original
    assert list(tmp_path.iterdir()) == [source]


def test_fix_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        apply_approved_fix(tmp_path, "../../etc/passwd", "root", "changed", True)
