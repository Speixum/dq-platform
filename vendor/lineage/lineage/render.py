"""血缘渲染：mermaid、graphviz dot、ASCII 文本树。"""

from __future__ import annotations

from typing import Any

STATUS_LABEL = {"ok": "ok", "failed": "FAILED"}
FAILED_FILL = "#fdd"


def _nodes(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in run.get("nodes") or [] if isinstance(node, dict)]


def _edges(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [edge for edge in run.get("edges") or [] if isinstance(edge, dict)]


def _index(nodes: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for position, node in enumerate(nodes):
        node_id = str(node.get("id", f"node{position}"))
        mapping[node_id] = f"n{position:02d}"
    return mapping


def _label(node: dict[str, Any]) -> str:
    step = str(node.get("step", "?"))
    status = STATUS_LABEL.get(str(node.get("status")), str(node.get("status")))
    duration = node.get("duration_ms")
    if isinstance(duration, (int, float)):
        return f"{step} | {status} | {duration:.1f}ms"
    return f"{step} | {status}"


def _escape(text: str) -> str:
    return text.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def to_mermaid(run: dict[str, Any], *, direction: str = "TD") -> str:
    """渲染成 mermaid flowchart；失败节点用红色 classDef failed fill:#fdd。"""
    nodes = _nodes(run)
    edges = _edges(run)
    index = _index(nodes)
    lines = ["flowchart " + direction]
    for node in nodes:
        node_id = index[str(node.get("id", ""))]
        label = _escape(_label(node)).replace("|", "<br/>")
        lines.append(f'  {node_id}["{label}"]')
    for edge in edges:
        source = index.get(str(edge.get("from")))
        target = index.get(str(edge.get("to")))
        if source is None or target is None:
            continue
        label = _escape(str(edge.get("label") or ""))
        if label:
            lines.append(f"  {source} -->|{label}| {target}")
        else:
            lines.append(f"  {source} --> {target}")
    failed = [
        index[str(node.get("id", ""))]
        for node in nodes
        if str(node.get("status")) == "failed"
    ]
    lines.append(f"  classDef failed fill:{FAILED_FILL}")
    if failed:
        lines.append(f"  class {','.join(failed)} failed")
    return "\n".join(lines) + "\n"


def to_dot(run: dict[str, Any]) -> str:
    """渲染成 graphviz dot；失败节点用浅红填充。"""
    nodes = _nodes(run)
    edges = _edges(run)
    index = _index(nodes)
    title = _escape(str(run.get("name") or run.get("run_id") or "lineage"))
    lines = [f'digraph "{title}" {{', "  rankdir=LR;", "  node [shape=box, fontsize=10];"]
    for node in nodes:
        node_id = index[str(node.get("id", ""))]
        label = _escape(_label(node).replace("|", "\\n"))
        if str(node.get("status")) == "failed":
            lines.append(
                f'  {node_id} [label="{label}", style=filled, fillcolor="{FAILED_FILL}", color="#c00"];'
            )
        else:
            lines.append(f'  {node_id} [label="{label}"];')
    for edge in edges:
        source = index.get(str(edge.get("from")))
        target = index.get(str(edge.get("to")))
        if source is None or target is None:
            continue
        label = _escape(str(edge.get("label") or ""))
        lines.append(f'  {source} -> {target} [label="{label}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_tree(run: dict[str, Any]) -> str:
    """渲染成纯 ASCII 文本树（只用 + - | 与空格）。"""
    nodes = _nodes(run)
    edges = _edges(run)
    index = _index(nodes)
    children: dict[str, list[str]] = {str(node.get("id")): [] for node in nodes}
    roots: list[str] = [str(node.get("id")) for node in nodes]
    for edge in edges:
        source = str(edge.get("from"))
        target = str(edge.get("to"))
        if source in children and target in children:
            children[source].append(target)
            if target in roots:
                roots.remove(target)
    by_id = {str(node.get("id")): node for node in nodes}
    title = str(run.get("name") or "lineage")
    status = str(run.get("status") or "unknown")
    lines = [f"{title} [{status}] nodes={len(nodes)} edges={len(edges)}"]

    def walk(node_id: str, prefix: str, is_last: bool) -> None:
        node = by_id[node_id]
        branch = "+-- " if is_last else "|-- "
        step = str(node.get("step", "?"))
        node_status = STATUS_LABEL.get(str(node.get("status")), str(node.get("status")))
        duration = node.get("duration_ms")
        suffix = f" ({duration:.1f} ms)" if isinstance(duration, (int, float)) else ""
        lines.append(f"{prefix}{branch}{node.get('seq', '?'):02d} {step} [{node_status}]{suffix}")
        child_prefix = prefix + ("    " if is_last else "|   ")
        for output in node.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            fingerprint = output.get("fingerprint") or {}
            shape = ""
            if isinstance(fingerprint, dict) and fingerprint:
                shape = (
                    f" rows={fingerprint.get('rows')} cols={fingerprint.get('cols')}"
                    f" null_ratio={fingerprint.get('null_ratio')}"
                )
            lines.append(
                f"{child_prefix}|-- {output.get('ref', '<return>')} "
                f"{output.get('kind', 'value')} {output.get('hash', '')}{shape}"
            )
        if node.get("status") == "failed":
            error = node.get("error") or {}
            lines.append(
                f"{child_prefix}|-- ! {error.get('type', 'Error')}: {error.get('message', '')}"
            )
        entries = children.get(node_id, [])
        for position, child in enumerate(entries):
            walk(child, child_prefix, position == len(entries) - 1)

    for position, root in enumerate(roots):
        walk(root, "", position == len(roots) - 1)
    return "\n".join(lines) + "\n"


def render(run: dict[str, Any], fmt: str = "tree") -> str:
    """按 fmt（mermaid/dot/tree）分发渲染。"""
    key = (fmt or "tree").lower()
    if key == "mermaid":
        return to_mermaid(run)
    if key == "dot":
        return to_dot(run)
    if key == "tree":
        return to_tree(run)
    raise ValueError(f"unknown render format: {fmt}")
