"""Repository inspection tools exposed to the analysis agent."""

from pathlib import Path
import re

from langchain_core.tools import tool


def _safe_path(repo_root: Path, requested_path: str) -> Path:
    """Resolve a repository path and reject paths outside the repository."""

    root = repo_root.resolve()
    candidate = (root / requested_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Requested path is outside the configured repository")
    return candidate


def validate_repository_root(repo_root: str | Path) -> Path:
    """Reject malformed or missing roots before invoking the model."""

    value = str(repo_root)
    if len(re.findall(r"[A-Za-z]:", value)) > 1:
        raise ValueError(
            "Некорректный путь репозитория: буква диска указана несколько раз. "
            "Укажите один полный путь без повторения префикса."
        )
    try:
        root = Path(value).expanduser().resolve()
        if root.is_dir():
            return root
    except (OSError, ValueError):
        pass
    raise ValueError(f"Папка репозитория не найдена: {value}. Проверьте поле пути к репозиторию.")


def build_repository_tools(repo_root: str | Path) -> list:
    """Build tools bound to one existing repository root."""

    root = validate_repository_root(repo_root)

    @tool
    def read_git_file(path: str) -> str:
        """Read a UTF-8 text file from the repository by its relative path."""

        file_path = _safe_path(root, path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Repository file not found: {path}")
        return file_path.read_text(encoding="utf-8")

    @tool
    def search_code_in_repo(query: str) -> str:
        """Find a text query in repository source files and return matching lines."""

        if not query.strip():
            raise ValueError("Search query must not be empty")

        matches: list[str] = []
        ignored_parts = {".git", ".venv", "__pycache__", ".pytest_cache"}
        for file_path in root.rglob("*"):
            if not file_path.is_file() or ignored_parts.intersection(file_path.parts):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(lines, start=1):
                if query.casefold() in line.casefold():
                    relative_path = file_path.relative_to(root)
                    matches.append(f"{relative_path}:{line_number}: {line.strip()}")
                    if len(matches) >= 50:
                        return "\n".join(matches)

        return "\n".join(matches) or "No matches found."

    @tool
    def list_repository_files() -> str:
        """List up to 200 real repository files to discover existing source paths."""
        ignored = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
        paths: list[str] = []
        for file_path in root.rglob("*"):
            relative = file_path.relative_to(root)
            if ignored.intersection(relative.parts) or ".backup-" in file_path.name:
                continue
            if not file_path.is_file():
                continue
            try:
                _safe_path(root, str(relative))
            except ValueError:
                continue
            paths.append(relative.as_posix())
            if len(paths) == 200:
                return "\n".join(paths) + "\n[Список ограничен; уточните поиск через search_code_in_repo.]"
        return "\n".join(paths) or "[Нет доступных файлов.]"

    return [read_git_file, search_code_in_repo, list_repository_files]
