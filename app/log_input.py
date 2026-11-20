"""Shared, bounded parsing of uploaded logs without writing copies."""

import json
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from app.schemas import LogPayload

MAX_UPLOAD_BYTES = 1024 * 1024
MAX_TEXT_CHARS = 12000


def parse_log(raw: bytes, filename: str | None) -> dict:
    if not raw.strip():
        raise HTTPException(400, "Файл лога пуст")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Лог превышает 1 МиБ. Выберите фрагмент вокруг ошибки")
    suffix = Path(filename or "log.json").suffix.lower()
    if suffix not in {".json", ".log", ".txt"}:
        raise HTTPException(400, "Поддерживаются файлы .json, .log и .txt")
    if suffix == ".json":
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(400, "Файл содержит невалидный JSON") from None
        if data == {}:
            raise HTTPException(400, "Лог должен быть непустым JSON-объектом")
        try:
            return LogPayload.model_validate(data).model_dump(exclude_none=True)
        except ValidationError as error:
            raise HTTPException(422, json.loads(error.json())) from None
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1251")
    except UnicodeDecodeError:
        raise HTTPException(400, "Не удалось прочитать текст. Сохраните лог в UTF-8") from None
    if not text.strip():
        raise HTTPException(400, "Файл лога пуст")
    if any(ord(char) < 32 and char not in "\r\n\t" for char in text):
        raise HTTPException(400, "Файл содержит двоичные данные. Нужен текстовый лог")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, "Текстовый лог превышает 12 000 символов. Выберите фрагмент вокруг ошибки со стеком вызовов")
    return {"log_format": "text", "message": text}


async def read_log_upload(file: UploadFile) -> dict:
    # Read at most the limit plus one byte, never an unbounded file into RAM.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    return parse_log(raw, file.filename)
