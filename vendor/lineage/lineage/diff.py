"""两次 run 的节点级 diff 与质量漂移。"""

from __future__ import annotations

from typing import Any

DIFF_SCHEMA = "lineage-diff/1.0"


def node_key(node: dict[str, Any], occurrence: int) -> str:
    """节点匹配键：step#出现序号，避免不同 run 的 seq 差异导致全部误报。"""
    return f"{node.get('step', '?')}#{occurrence:02d}"


def _keyed(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """把 run 的节点按 (step, 出现序号) 建索引。"""
    counters: dict[str, int] = {}
    keyed: dict[str, dict[str, Any]] = {}
    for node in run.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        step = str(node.get("step", "?"))
        counters[step] = counters.get(step, 0) + 1
        keyed[node_key(node, counters[step])] = node
    return keyed


def _output_map(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for output in node.get("outputs") or []:
        if isinstance(output, dict):
            mapping[str(output.get("ref", "<return>"))] = output
    return mapping


def _hash_of(node: dict[str, Any]) -> str:
    hashes = sorted(
        str(output.get("hash"))
        for output in node.get("outputs") or []
        if isinstance(output, dict)
    )
    return "|".join(hashes)


def _drift(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """比较同一 ref 的质量指纹，给出 rows / null_ratio 的变化。"""
    old_fp = old.get("fingerprint") if isinstance(old.get("fingerprint"), dict) else {}
    new_fp = new.get("fingerprint") if isinstance(new.get("fingerprint"), dict) else {}
    if not old_fp and not new_fp:
        return {}
    old_rows = old_fp.get("rows") if isinstance(old_fp.get("rows"), int) else None
    new_rows = new_fp.get("rows") if isinstance(new_fp.get("rows"), int) else None
    old_null = old_fp.get("null_ratio") if isinstance(old_fp.get("null_ratio"), (int, float)) else None
    new_null = new_fp.get("null_ratio") if isinstance(new_fp.get("null_ratio"), (int, float)) else None
    rows_delta = (new_rows - old_rows) if (old_rows is not None and new_rows is not None) else None
    null_delta = (
        round(abs(float(new_null) - float(old_null)), 4)
        if (old_null is not None and new_null is not None)
        else None
    )
    drift = {
        "rows": [old_rows, new_rows],
        "rows_delta": rows_delta,
        "null_ratio": [old_null, new_null],
        "null_ratio_delta": null_delta,
        "dup_rows": [
            old_fp.get("dup_rows"),
            new_fp.get("dup_rows"),
        ],
    }
    drift["has_drift"] = bool(
        (rows_delta not in (None, 0)) or (null_delta not in (None, 0.0))
    )
    return drift


def diff_runs(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """比较两次 run：新增/消失节点、哈希变化、质量漂移。"""
    old_keyed = _keyed(before)
    new_keyed = _keyed(after)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    for key, node in new_keyed.items():
        if key not in old_keyed:
            added.append(
                {
                    "key": key,
                    "id": node.get("id"),
                    "step": node.get("step"),
                    "status": node.get("status"),
                }
            )
    for key, node in old_keyed.items():
        if key not in new_keyed:
            removed.append(
                {
                    "key": key,
                    "id": node.get("id"),
                    "step": node.get("step"),
                    "status": node.get("status"),
                }
            )

    for key in sorted(new_keyed):
        if key not in old_keyed:
            continue
        old_node = old_keyed[key]
        new_node = new_keyed[key]
        old_outputs = _output_map(old_node)
        new_outputs = _output_map(new_node)
        output_diffs: list[dict[str, Any]] = []
        for ref in sorted(set(old_outputs) | set(new_outputs)):
            old_output = old_outputs.get(ref)
            new_output = new_outputs.get(ref)
            old_hash = old_output.get("hash") if old_output else None
            new_hash = new_output.get("hash") if new_output else None
            drift = _drift(old_output or {}, new_output or {})
            if old_hash == new_hash and not drift.get("has_drift") and old_output and new_output:
                continue
            output_diffs.append(
                {
                    "ref": ref,
                    "hash_before": old_hash,
                    "hash_after": new_hash,
                    "hash_changed": old_hash != new_hash,
                    "drift": drift,
                }
            )
        status_before = old_node.get("status")
        status_after = new_node.get("status")
        params_changed = old_node.get("params") != new_node.get("params")
        duration_before = old_node.get("duration_ms")
        duration_after = new_node.get("duration_ms")
        if (
            not output_diffs
            and status_before == status_after
            and not params_changed
        ):
            continue
        changed.append(
            {
                "key": key,
                "id": new_node.get("id"),
                "step": new_node.get("step"),
                "status_before": status_before,
                "status_after": status_after,
                "status_changed": status_before != status_after,
                "params_changed": params_changed,
                "duration_ms_before": duration_before,
                "duration_ms_after": duration_after,
                "outputs": output_diffs,
            }
        )

    drifted = sum(
        1
        for item in changed
        for output in item.get("outputs") or []
        if (output.get("drift") or {}).get("has_drift")
    )
    return {
        "schema": DIFF_SCHEMA,
        "before": {
            "run_id": before.get("run_id"),
            "name": before.get("name"),
            "status": before.get("status"),
        },
        "after": {
            "run_id": after.get("run_id"),
            "name": after.get("name"),
            "status": after.get("status"),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": max(
                0, len(set(old_keyed) & set(new_keyed)) - len(changed)
            ),
            "quality_drift": drifted,
            "status_changed": before.get("status") != after.get("status"),
            "identical": not added and not removed and not changed,
        },
    }


def format_text(result: dict[str, Any]) -> str:
    """把 diff 结果渲染成 ASCII 表格文本。"""
    lines: list[str] = []
    before = result.get("before") or {}
    after = result.get("after") or {}
    lines.append(f"before: {before.get('name')} ({before.get('status')})")
    lines.append(f"after : {after.get('name')} ({after.get('status')})")
    summary = result.get("summary") or {}
    lines.append(
        "summary: added={0} removed={1} changed={2} unchanged={3} drift={4}".format(
            summary.get("added", 0),
            summary.get("removed", 0),
            summary.get("changed", 0),
            summary.get("unchanged", 0),
            summary.get("quality_drift", 0),
        )
    )
    lines.append("")

    def table(headers: list[str], rows: list[list[str]]) -> None:
        if not rows:
            return
        widths = [len(header) for header in headers]
        for row in rows:
            for position, cell in enumerate(row):
                widths[position] = max(widths[position], len(cell))
        separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
        lines.append(separator)
        lines.append(
            "|" + "|".join(f" {header:<{widths[i]}} " for i, header in enumerate(headers)) + "|"
        )
        lines.append(separator)
        for row in rows:
            lines.append(
                "|"
                + "|".join(f" {cell:<{widths[i]}} " for i, cell in enumerate(row))
                + "|"
            )
        lines.append(separator)

    if result.get("added"):
        lines.append("added nodes:")
        table(
            ["key", "id"],
            [[str(item.get("key")), str(item.get("id"))] for item in result["added"]],
        )
        lines.append("")
    if result.get("removed"):
        lines.append("removed nodes:")
        table(
            ["key", "id"],
            [[str(item.get("key")), str(item.get("id"))] for item in result["removed"]],
        )
        lines.append("")
    if result.get("changed"):
        lines.append("changed nodes:")
        rows = []
        for item in result["changed"]:
            drifts = [
                output.get("drift") or {}
                for output in item.get("outputs") or []
                if (output.get("drift") or {}).get("has_drift")
            ]
            drift_text = "; ".join(
                "rows {0}->{1} null {2}->{3}".format(
                    (drift.get("rows") or [None, None])[0],
                    (drift.get("rows") or [None, None])[1],
                    (drift.get("null_ratio") or [None, None])[0],
                    (drift.get("null_ratio") or [None, None])[1],
                )
                for drift in drifts
            )
            rows.append(
                [
                    str(item.get("step")),
                    f"{item.get('status_before')} -> {item.get('status_after')}",
                    "yes" if item.get("params_changed") else "no",
                    str(len(item.get("outputs") or [])),
                    drift_text or "-",
                ]
            )
        table(["step", "status", "params", "outputs", "drift"], rows)
        lines.append("")
    if summary.get("identical"):
        lines.append("no differences.")
    return "\n".join(lines).rstrip() + "\n"
