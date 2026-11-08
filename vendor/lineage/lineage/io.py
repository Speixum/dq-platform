"""JSON 读写与血缘文件加载。"""

from __future__ import annotations

import json
import os
from typing import Any

from .errors import LineageError, LineageFormatError

LINEAGE_SCHEMA = "dataset-lineage/1.0"


def load_json(path: str | os.PathLike[str]) -> Any:
    """读取 UTF-8 JSON；缺失或解析失败时抛 LineageError（信息为 ASCII）。"""
    target = os.fspath(path)
    try:
        with open(target, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise LineageError(f"file not found: {target}") from exc
    except IsADirectoryError as exc:
        raise LineageError(f"not a file: {target}") from exc
    except json.JSONDecodeError as exc:
        raise LineageFormatError(
            f"invalid json in {target}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise LineageError(f"cannot read file: {target} ({exc.strerror or exc})") from exc
    except UnicodeDecodeError as exc:
        raise LineageFormatError(f"file is not valid utf-8: {target}") from exc


def save_json(path: str | os.PathLike[str], data: Any) -> str:
    """写出 UTF-8 JSON（缩进 2、不转义中文、末尾换行），返回绝对路径。"""
    target = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target


def save_text(path: str | os.PathLike[str], text: str) -> str:
    """写出 UTF-8 文本文件，返回绝对路径。"""
    target = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return target


def load_lineage(path: str | os.PathLike[str]) -> dict[str, Any]:
    """加载并校验血缘 JSON；schema 不匹配时抛 LineageFormatError。"""
    data = load_json(path)
    if not isinstance(data, dict):
        raise LineageFormatError(f"lineage file must be a json object: {os.fspath(path)}")
    schema = data.get("schema")
    if not isinstance(schema, str) or not schema.startswith("dataset-lineage/"):
        raise LineageFormatError(
            f"not a lineage file (schema={schema!r}): {os.fspath(path)}"
        )
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise LineageFormatError(f"lineage file has no nodes list: {os.fspath(path)}")
    return data
