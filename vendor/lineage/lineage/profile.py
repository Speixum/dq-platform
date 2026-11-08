"""表格质量指纹：纯标准库的存量指标（行数/列数/缺失率/重复行/类型推断）。"""

from __future__ import annotations

import re
from typing import Any

from .hashing import as_records, is_dataframe, is_table

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")

_BOOL_TRUE = {"true", "yes", "y", "1"}
_BOOL_FALSE = {"false", "no", "n", "0"}

TYPES = ("empty", "bool", "int", "float", "date", "datetime", "str", "mixed")


def is_null(value: Any) -> bool:
    """缺失判定：None 或空字符串（不做 strip，避免篡改原始内容）。"""
    return value is None or value == ""


def classify(value: Any) -> str:
    """把单个非空单元格归类为 bool/int/float/date/datetime/str。"""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "str"
        lowered = text.lower()
        if lowered in _BOOL_TRUE or lowered in _BOOL_FALSE:
            return "bool"
        if _INT_RE.match(text):
            return "int"
        if _FLOAT_RE.match(text):
            return "float"
        if _DATETIME_RE.match(text):
            return "datetime"
        if _DATE_RE.match(text):
            return "date"
        return "str"
    return "str"


def infer_type(values: list[Any]) -> str:
    """一列的类型推断：全空为 empty，多种类型为 mixed。"""
    seen: set[str] = set()
    for value in values:
        if is_null(value):
            continue
        seen.add(classify(value))
    if not seen:
        return "empty"
    if len(seen) == 1:
        return next(iter(seen))
    if seen <= {"int", "float"}:
        return "float"
    return "mixed"


def profile_table(rows: Any) -> dict[str, Any]:
    """计算表格质量指纹。

    返回 ``{rows, cols, columns, null_ratio, dup_rows, types}``。
    ``dup_rows`` 为"重复出现的行数"（总行数 - 去重后行数），``null_ratio`` 为全表缺失单元格占比。
    """
    if not is_table(rows):
        return {
            "rows": 0,
            "cols": 0,
            "columns": [],
            "null_ratio": 0.0,
            "dup_rows": 0,
            "types": {},
        }
    columns, records = as_records(rows)
    total_rows = len(records)
    total_cells = total_rows * len(columns)
    null_cells = 0
    type_values: dict[str, list[Any]] = {column: [] for column in columns}
    seen_rows: set[tuple[Any, ...]] = set()
    duplicate_rows = 0
    for record in records:
        key = tuple(
            repr(record.get(column)) if not is_null(record.get(column)) else None
            for column in columns
        )
        if key in seen_rows:
            duplicate_rows += 1
        else:
            seen_rows.add(key)
        for column in columns:
            value = record.get(column)
            if is_null(value):
                null_cells += 1
            else:
                type_values[column].append(value)
    null_ratio = round(null_cells / total_cells, 4) if total_cells else 0.0
    return {
        "rows": total_rows,
        "cols": len(columns),
        "columns": list(columns),
        "null_ratio": null_ratio,
        "dup_rows": duplicate_rows,
        "types": {column: infer_type(values) for column, values in type_values.items()},
    }
