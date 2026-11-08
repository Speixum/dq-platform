"""内容哈希：文件分块 sha256、表格规范化哈希、不可序列化对象的降级哈希。

约定：
- 所有哈希字符串带 ``sha256:`` 前缀；
- 文件按 1MB 分块读取，不一次性读入内存；
- 表格哈希与列顺序无关、与行序有关，并保留列名；
- 无法稳定哈希的对象返回 ``unstable:<type>#<short>``。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .errors import LineageError

PREFIX = "sha256:"
CHUNK_SIZE = 1024 * 1024
MAX_DEPTH = 6

_RECORD_TYPES = (list, tuple)


def sha256_bytes(data: bytes) -> str:
    """返回字节串的 sha256，带 ``sha256:`` 前缀。"""
    return PREFIX + hashlib.sha256(data).hexdigest()


def hash_file(path: str | os.PathLike[str], chunk_size: int = CHUNK_SIZE) -> str:
    """按块读取文件并返回 sha256；文件缺失/不可读时抛 LineageError。"""
    if chunk_size <= 0:
        raise LineageError("chunk_size must be positive")
    target = os.fspath(path)
    digest = hashlib.sha256()
    try:
        with open(target, "rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise LineageError(f"file not found: {target}") from exc
    except IsADirectoryError as exc:
        raise LineageError(f"not a file: {target}") from exc
    except OSError as exc:
        raise LineageError(f"cannot read file: {target} ({exc.strerror or exc})") from exc
    return PREFIX + digest.hexdigest()


def is_dataframe(obj: Any) -> bool:
    """用 hasattr 探测 pandas DataFrame，绝不 import pandas。"""
    if obj is None or isinstance(obj, (str, bytes, dict, list, tuple, set)):
        return False
    return (
        hasattr(obj, "columns")
        and hasattr(obj, "to_dict")
        and hasattr(obj, "shape")
    )


def _is_columnar(obj: Any) -> bool:
    """dict[str, list] 形式的列式表格。"""
    return (
        isinstance(obj, dict)
        and bool(obj)
        and all(isinstance(value, _RECORD_TYPES) for value in obj.values())
    )


def is_table(obj: Any) -> bool:
    """判断对象是否可作为表格处理（dict 行列表 / 二维行列表 / 列式 dict / DataFrame）。"""
    if is_dataframe(obj):
        return True
    if _is_columnar(obj):
        return True
    if isinstance(obj, _RECORD_TYPES) and obj:
        return all(
            isinstance(row, dict)
            or (isinstance(row, _RECORD_TYPES))
            for row in obj
        )
    return False


def as_records(obj: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """把表格对象统一成 (首次出现顺序的列名, 行字典列表)。

    支持 list[dict]、二维 list/tuple、dict[str, list] 与 DataFrame 鸭子类型。
    参差不齐的行用 None 补齐，不抛异常。
    """
    if is_dataframe(obj):
        columns = [str(name) for name in list(obj.columns)]
        records = obj.to_dict(orient="records")
        rows = [{str(key): value for key, value in dict(record).items()} for record in records]
        return columns, rows

    if _is_columnar(obj):
        columns = [str(key) for key in obj.keys()]
        width = max((len(value) for value in obj.values()), default=0)
        rows = []
        for index in range(width):
            rows.append(
                {
                    column: (obj[column][index] if index < len(obj[column]) else None)
                    for column in obj
                }
            )
        return columns, rows

    if isinstance(obj, _RECORD_TYPES):
        rows_in = list(obj)
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows_in:
            if isinstance(row, dict):
                for key in row:
                    name = str(key)
                    if name not in seen:
                        seen.add(name)
                        columns.append(name)
        if columns:
            records = []
            for row in rows_in:
                if isinstance(row, dict):
                    records.append({str(k): v for k, v in row.items()})
                else:
                    padded = list(row)
                    record = {name: None for name in columns}
                    for index, name in enumerate(columns):
                        if index < len(padded):
                            record[name] = padded[index]
                    records.append(record)
            return columns, records

        width = max((len(row) for row in rows_in), default=0)
        columns = [f"c{index}" for index in range(width)]
        records = []
        for row in rows_in:
            padded = list(row) + [None] * (width - len(row))
            records.append(dict(zip(columns, padded)))
        return columns, records

    raise LineageError("object is not a table")


def normalise_cell(value: Any) -> Any:
    """把单元格规范化为 JSON 可编码、跨进程稳定的形式。"""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return repr(value)
    except Exception:  # pragma: no cover - repr 极少失败
        return f"<{type(value).__name__}>"


def hash_table(obj: Any) -> str:
    """表格内容哈希：列名排序后逐行规范化编码，行序影响结果、列序不影响。"""
    columns, records = as_records(obj)
    ordered = sorted(columns)
    digest = hashlib.sha256()
    digest.update(b"table/1\n")
    digest.update(
        json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    digest.update(b"\n")
    for record in records:
        row = [normalise_cell(record.get(column)) for column in ordered]
        digest.update(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return PREFIX + digest.hexdigest()


def hash_json(value: Any) -> str:
    """对已 JSON 化的值做稳定哈希（键排序、紧凑分隔）。"""
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256_bytes(payload.encode("utf-8"))


def short(text: str, length: int = 8) -> str:
    """返回字符串 sha256 的前 `length` 位十六进制。"""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:length]


def json_snapshot(value: Any, _depth: int = 0) -> tuple[Any, bool]:
    """把任意对象转成可 JSON 序列化的快照，返回 (快照, 是否不稳定)。"""
    if _depth > MAX_DEPTH:
        return f"<depth-limit:{type(value).__name__}>", True
    if value is None or isinstance(value, (bool, int, str)):
        return value, False
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN", False
        if math.isinf(value):
            return ("Infinity" if value > 0 else "-Infinity"), False
        return value, False
    if isinstance(value, Path):
        return str(value), False
    if isinstance(value, datetime):
        return value.isoformat(), False
    if isinstance(value, date):
        return value.isoformat(), False
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>", False
    if not isinstance(value, (dict, list, tuple)) or is_table(value):
        if is_table(value):
            # 表格在 params 里只留结构摘要（完整哈希另有输入/输出字段），摘要本身是稳定的。
            columns, records = as_records(value)
            return {"<table>": columns, "<rows>": len(records)}, False
    if isinstance(value, dict):
        snapshot: dict[str, Any] = {}
        unstable = False
        for key, item in value.items():
            name = key if isinstance(key, str) else repr(key)
            if not isinstance(key, str):
                unstable = True
            converted, item_unstable = json_snapshot(item, _depth + 1)
            snapshot[name] = converted
            unstable = unstable or item_unstable
        return snapshot, unstable
    if isinstance(value, (list, tuple)):
        items = []
        unstable = False
        for item in value:
            converted, item_unstable = json_snapshot(item, _depth + 1)
            items.append(converted)
            unstable = unstable or item_unstable
        return items, unstable
    if isinstance(value, (set, frozenset)):
        try:
            ordered = sorted(value, key=repr)
        except TypeError:  # pragma: no cover
            ordered = list(value)
        items = []
        unstable = False
        for item in ordered:
            converted, item_unstable = json_snapshot(item, _depth + 1)
            items.append(converted)
            unstable = unstable or item_unstable
        return items, unstable
    try:
        return repr(value), True
    except Exception:  # pragma: no cover
        return f"<{type(value).__name__}>", True


def unstable_hash(obj: Any) -> str:
    """不可稳定哈希对象的占位哈希：``unstable:<type>#<short>``。"""
    try:
        text = repr(obj)
    except Exception:  # pragma: no cover
        text = f"<{type(obj).__name__}>"
    return f"unstable:{type(obj).__name__}#{short(text)}"


def _looks_like_path(value: str) -> bool:
    return bool(value) and len(value) < 4096 and "\n" not in value and os.path.isfile(value)


def fingerprint_object(obj: Any, ref: str = "<return>") -> dict[str, Any]:
    """为一个输入/输出生成 {ref, kind, hash, bytes, [fingerprint], [unstable]}。"""
    if isinstance(obj, str) and _looks_like_path(obj):
        try:
            size = os.path.getsize(obj)
        except OSError:
            size = None
        return {
            "ref": ref,
            "kind": "file",
            "hash": hash_file(obj),
            "bytes": size,
        }
    if is_table(obj):
        from .profile import profile_table

        return {
            "ref": ref,
            "kind": "table",
            "hash": hash_table(obj),
            "bytes": None,
            "fingerprint": profile_table(obj),
        }
    snapshot, unstable = json_snapshot(obj)
    entry: dict[str, Any] = {
        "ref": ref,
        "kind": "value",
        "hash": unstable_hash(obj) if unstable else hash_json(snapshot),
        "bytes": None,
    }
    if unstable:
        entry["unstable"] = True
    return entry
