"""Repository inspection tools exposed to the analysis agent."""

from pathlib import Path

from langchain_core.tools import tool


def _safe_path(repo_root: Path, requested_path: str) -> Path:
    """Resolve a repository path and reject paths outside the repository."""

    root = repo_root.resolve()
    candidate = (root / requested_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Requested path is outside the configured repository")
    return candidate


def build_repository_tools(repo_root: str | Path) -> list:
    """Build tools bound to one repository root."""

    root = Path(repo_root).resolve()

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

    return [read_git_file, search_code_in_repo]