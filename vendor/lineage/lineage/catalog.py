"""数据集卡片与 catalog.json 聚合。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

from .errors import LineageError, LineageFormatError
from .io import load_json, save_json, save_text

CATALOG_SCHEMA = "dataset-catalog/1.0"
DEFAULT_LICENSE = "internal-only"
DEFAULT_TASKS = ("analytics",)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dataset_from_run(run: dict[str, Any]) -> dict[str, Any]:
    """从血缘 JSON 里提取"最终数据集"的规模信息（最后一个 ok 节点的表格输出）。"""
    nodes = run.get("nodes") or []
    for node in reversed(nodes):
        if not isinstance(node, dict) or node.get("status") != "ok":
            continue
        for output in node.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            fingerprint = output.get("fingerprint")
            if output.get("kind") == "table" and isinstance(fingerprint, dict):
                return {
                    "rows": fingerprint.get("rows"),
                    "cols": fingerprint.get("cols"),
                    "columns": list(fingerprint.get("columns") or []),
                    "null_ratio": fingerprint.get("null_ratio"),
                    "dup_rows": fingerprint.get("dup_rows"),
                    "types": dict(fingerprint.get("types") or {}),
                    "hash": output.get("hash"),
                    "source_step": node.get("step"),
                }
    return {}


def make_entry(
    run: dict[str, Any],
    *,
    name: str | None = None,
    version: str = "1.0.0",
    license: str = DEFAULT_LICENSE,
    tasks: Iterable[str] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """把一次 run 汇总成 catalog 条目（名称/版本/规模/字段/许可/任务/更新时间）。"""
    dataset = dataset_from_run(run)
    run_name = str(run.get("name") or "unnamed")
    entry_name = name or run_name
    columns = dataset.get("columns") or []
    return {
        "name": entry_name,
        "version": version,
        "rows": dataset.get("rows"),
        "cols": dataset.get("cols", len(columns)),
        "columns": columns,
        "null_ratio": dataset.get("null_ratio"),
        "dup_rows": dataset.get("dup_rows"),
        "types": dataset.get("types") or {},
        "hash": dataset.get("hash"),
        "license": license,
        "tasks": list(tasks) if tasks is not None else list(DEFAULT_TASKS),
        "updated_at": updated_at or run.get("finished_at") or _utc_now(),
        "source_run": run.get("run_id"),
        "source_step": dataset.get("source_step"),
        "status": run.get("status"),
        "card": f"cards/{entry_name}.md",
    }


def build_catalog(entries: Iterable[dict[str, Any]], *, generated_at: str | None = None) -> dict[str, Any]:
    """把条目聚合成 catalog（同一 name+version 去重，后者覆盖前者）。"""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (str(entry.get("name")), str(entry.get("version")))
        merged[key] = entry
    datasets = [merged[key] for key in sorted(merged)]
    return {
        "schema": CATALOG_SCHEMA,
        "generated_at": generated_at or _utc_now(),
        "datasets": datasets,
    }


def upsert(catalog: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """把条目写入已有 catalog，返回新 catalog（不修改入参）。"""
    entries = [item for item in catalog.get("datasets") or [] if isinstance(item, dict)]
    entries.append(entry)
    return build_catalog(entries, generated_at=_utc_now())


def load_catalog(path: str) -> dict[str, Any]:
    """读取 catalog.json；schema 不匹配时抛 LineageFormatError。"""
    data = load_json(path)
    if not isinstance(data, dict):
        raise LineageFormatError(f"catalog must be a json object: {path}")
    if data.get("schema") != CATALOG_SCHEMA:
        raise LineageFormatError(
            f"not a catalog file (schema={data.get('schema')!r}): {path}"
        )
    if not isinstance(data.get("datasets"), list):
        raise LineageFormatError(f"catalog has no datasets list: {path}")
    return data


def write_catalog(path: str, catalog: dict[str, Any]) -> str:
    """写出 catalog.json，返回绝对路径。"""
    return save_json(path, catalog)


def _fmt(value: Any, placeholder: str = "-") -> str:
    if value is None or value == "":
        return placeholder
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def card_markdown(entry: dict[str, Any]) -> str:
    """生成数据集卡片 markdown（名称/版本/规模/字段/许可/适用任务/更新时间）。"""
    columns = list(entry.get("columns") or [])
    types = dict(entry.get("types") or {})
    fingerprint_types = types or {}
    rows = entry.get("rows")
    cols = entry.get("cols")
    size = f"{_fmt(rows, '?')} 行 x {_fmt(cols, '?')} 列"
    tasks = entry.get("tasks") or []
    task_text = "、".join(str(task) for task in tasks) if tasks else "-"
    lines = [
        f"# 数据集卡片：{_fmt(entry.get('name'))}",
        "",
        f"- 名称：{_fmt(entry.get('name'))}",
        f"- 版本：{_fmt(entry.get('version'))}",
        f"- 规模：{size}",
        f"- 许可：{_fmt(entry.get('license'))}",
        f"- 适用任务：{task_text}",
        f"- 更新时间：{_fmt(entry.get('updated_at'))}",
        f"- 来源运行：{_fmt(entry.get('source_run'))}",
        f"- 生成步骤：{_fmt(entry.get('source_step'))}",
        f"- 内容哈希：{_fmt(entry.get('hash'))}",
        f"- 缺失率：{_fmt(entry.get('null_ratio'))}",
        f"- 重复行：{_fmt(entry.get('dup_rows'), '0')}",
        "",
        "## 字段",
        "",
    ]
    if columns:
        lines.append("| 列名 | 推断类型 |")
        lines.append("| --- | --- |")
        for column in columns:
            lines.append(f"| {column} | {fingerprint_types.get(column, '-')} |")
    else:
        lines.append("（无字段信息：该 run 没有表格输出）")
    lines.append("")
    return "\n".join(lines)


def write_card(directory: str, entry: dict[str, Any]) -> str:
    """把卡片写入 ``<directory>/<name>.md``，返回绝对路径。"""
    name = str(entry.get("name") or "dataset")
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in name)
    return save_text(os.path.join(directory, f"{safe}.md"), card_markdown(entry))


def collect_entries(
    directory: str,
    *,
    versions: dict[str, str] | None = None,
    license: str = DEFAULT_LICENSE,
    tasks: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """扫描目录下所有血缘 JSON，生成 catalog 条目（按名称+版本去重）。"""
    from .io import load_lineage

    if not os.path.isdir(directory):
        raise LineageError(f"not a directory: {directory}")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for filename in sorted(os.listdir(directory)):
        if not filename.lower().endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        try:
            run_data = load_lineage(path)
        except LineageError:
            continue
        run_name = str(run_data.get("name") or filename[:-5])
        if run_name in seen:
            continue
        seen.add(run_name)
        version = (versions or {}).get(run_name, "1.0.0")
        try:
            entries.append(
                make_entry(
                    run_data,
                    name=run_name,
                    version=version,
                    license=license,
                    tasks=tasks,
                )
            )
        except LineageError:
            continue  # 单文件异常不影响整体聚合
    return entries
