from pathlib import Path

import pytest

from app.tools import build_repository_tools


def test_read_git_file_reads_only_from_repository(tmp_path: Path) -> None:
    source_file = tmp_path / "module.py"
    source_file.write_text("DIRECTUM_ERROR = 'boom'\n", encoding="utf-8")
    read_file = build_repository_tools(tmp_path)[0]

    assert "DIRECTUM_ERROR" in read_file.invoke({"path": "module.py"})

    with pytest.raises(ValueError):
        read_file.invoke({"path": "../../etc/passwd"})


def test_search_code_in_repo_returns_file_and_line(tmp_path: Path) -> None:
    source_file = tmp_path / "service.py"
    source_file.write_text("raise RuntimeError('Directum timeout')\n", encoding="utf-8")
    search = build_repository_tools(tmp_path)[1]

    result = search.invoke({"query": "Directum timeout"})

    assert "service.py:1" in result