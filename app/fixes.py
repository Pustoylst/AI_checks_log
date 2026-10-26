"""Safe, explicitly approved code changes."""

from datetime import datetime
from pathlib import Path

from app.tools import _safe_path


def apply_approved_fix(repo_root: str | Path, path: str, old_text: str, new_text: str, approved: bool) -> tuple[str, str]:
    """Apply one exact replacement after checking explicit approval and file state."""

    if not approved:
        raise PermissionError("Изменение не применено: требуется явное подтверждение пользователя")
    if not old_text.strip():
        raise ValueError("Предыдущий фрагмент кода не может быть пустым")
    if old_text == new_text:
        raise ValueError("Новое содержимое совпадает со старым")

    file_path = _safe_path(Path(repo_root), path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    current_text = file_path.read_text(encoding="utf-8")
    if current_text.count(old_text) != 1:
        raise ValueError("Исходный фрагмент не найден ровно один раз; файл не изменён")

    backup_path = file_path.with_name(f"{file_path.name}.backup-{datetime.now():%Y%m%d%H%M%S}")
    backup_path.write_text(current_text, encoding="utf-8")
    file_path.write_text(current_text.replace(old_text, new_text, 1), encoding="utf-8")
    return str(file_path.relative_to(Path(repo_root).resolve())), str(backup_path)