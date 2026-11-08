"""跨工具 JSON 契约的最小校验。

只做结构检查（schema 标识 + 必有字段 + 关键字段类型），不做 JSON Schema 全量校验；
目的是在流水线里尽早发现"产物不是这个工具说的那个格式"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PII_SCHEMA = "pii-hits/1.0"
LINEAGE_SCHEMA = "dataset-lineage/1.0"
REPORT_SCHEMA = "data-quality-report/1.0"

#: schema -> (必有字段, 必须是 list 的字段, 必须是 dict 的字段)
SPECS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    PII_SCHEMA: (("schema", "source", "findings", "summary"), ("findings",), ("summary",)),
    LINEAGE_SCHEMA: (
        ("schema", "run_id", "status", "nodes", "edges"),
        ("nodes", "edges"),
        (),
    ),
    REPORT_SCHEMA: (("schema", "subject", "summary", "dimensions"), ("dimensions",), ("subject", "summary")),
}


def load_json(path: str | Path) -> Any:
    """读取 JSON；解析失败抛 ValueError。"""
    target = Path(path)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {target}: {exc}") from exc


def validate_payload(payload: Any) -> list[str]:
    """校验一个已解析的 JSON 对象，返回问题列表（空表示通过）。"""
    if not isinstance(payload, dict):
        return ["top-level value must be an object"]
    schema = payload.get("schema")
    if not isinstance(schema, str):
        return ["missing 'schema' string"]
    spec = SPECS.get(schema)
    if spec is None:
        known = ", ".join(sorted(SPECS))
        return [f"unknown schema {schema!r} (known: {known})"]

    required, list_keys, dict_keys = spec
    problems: list[str] = []
    for key in required:
        if key not in payload:
            problems.append(f"missing key {key!r}")
    for key in list_keys:
        if key in payload and not isinstance(payload[key], list):
            problems.append(f"{key!r} must be a list")
    for key in dict_keys:
        if key in payload and not isinstance(payload[key], dict):
            problems.append(f"{key!r} must be an object")

    if schema == PII_SCHEMA:
        for index, item in enumerate(payload.get("findings") or []):
            if not isinstance(item, dict):
                problems.append(f"findings[{index}] must be an object")
                break
            if "type" not in item or "confidence" not in item:
                problems.append(f"findings[{index}] lacks 'type' or 'confidence'")
                break
    elif schema == LINEAGE_SCHEMA:
        for index, item in enumerate(payload.get("nodes") or []):
            if not isinstance(item, dict):
                problems.append(f"nodes[{index}] must be an object")
                break
            if "status" not in item:
                problems.append(f"nodes[{index}] lacks 'status'")
                break
    return problems


def validate_file(path: str | Path) -> list[str]:
    """校验单个 JSON 产物文件。"""
    try:
        payload = load_json(path)
    except ValueError as exc:
        return [str(exc)]
    return validate_payload(payload)
