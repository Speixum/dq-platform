"""命令行入口：lineage render|diff|show|list|catalog|card。

约定：标准输出做 UTF-8 安全处理；表格骨架只用 ASCII 符号；错误信息为 ASCII。
退出码：0 成功，1 运行期错误，2 参数错误（argparse）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence

from . import __version__
from .catalog import (
    DEFAULT_LICENSE,
    card_markdown,
    collect_entries,
    make_entry,
    build_catalog,
    write_card,
    write_catalog,
)
from .diff import diff_runs, format_text
from .errors import LineageError
from .io import load_lineage, save_text
from .render import render

_TABLE_SEP = "+"


def _setup_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8，避免 Windows 控制台编码崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 重定向流可能不支持
            pass


def ascii_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """生成 ASCII 表格（+ - | 骨架，单元格内容原样保留）。"""
    cells = [["" if value is None else str(value) for value in row] for row in rows]
    widths = [len(str(header)) for header in headers]
    for row in cells:
        for position, cell in enumerate(row):
            if position < len(widths):
                widths[position] = max(widths[position], len(cell))
    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    lines = [separator]
    lines.append(
        "|"
        + "|".join(f" {str(header):<{widths[i]}} " for i, header in enumerate(headers))
        + "|"
    )
    lines.append(separator)
    for row in cells:
        padded = list(row) + [""] * (len(widths) - len(row))
        lines.append(
            "|" + "|".join(f" {cell:<{widths[i]}} " for i, cell in enumerate(padded)) + "|"
        )
    lines.append(separator)
    return "\n".join(lines)


def _emit(text: str, out: str | None) -> None:
    if out:
        path = save_text(out, text if text.endswith("\n") else text + "\n")
        print(f"wrote {path}")
    else:
        print(text if not text.endswith("\n") else text[:-1])


def _load(path: str) -> dict[str, Any]:
    return load_lineage(path)


def cmd_render(args: argparse.Namespace) -> int:
    data = _load(args.path)
    _emit(render(data, args.format), args.out)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    before = _load(args.before)
    after = _load(args.after)
    result = diff_runs(before, after)
    if args.json:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = format_text(result)
    _emit(text, args.out)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    data = _load(args.path)
    nodes = [node for node in data.get("nodes") or [] if isinstance(node, dict)]
    if args.node:
        for node in nodes:
            if str(node.get("id")) == args.node or str(node.get("step")) == args.node:
                print(json.dumps(node, ensure_ascii=False, indent=2))
                return 0
        print(f"error: node not found: {args.node}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    failed = sum(1 for node in nodes if node.get("status") == "failed")
    print(f"run   : {data.get('name')}")
    print(f"run_id: {data.get('run_id')}")
    print(f"status: {data.get('status')}  nodes: {len(nodes)}  failed: {failed}")
    print(f"window: {data.get('started_at')} -> {data.get('finished_at')}")
    rows = []
    for node in nodes:
        fingerprint = {}
        for output in node.get("outputs") or []:
            if isinstance(output, dict) and isinstance(output.get("fingerprint"), dict):
                fingerprint = output["fingerprint"]
                break
        duration = node.get("duration_ms")
        rows.append(
            [
                f"{node.get('seq', '?'):02d}" if isinstance(node.get("seq"), int) else "?",
                str(node.get("step")),
                str(node.get("status")),
                f"{duration:.1f}" if isinstance(duration, (int, float)) else "-",
                f"{fingerprint.get('rows', '-')}x{fingerprint.get('cols', '-')}"
                if fingerprint
                else "-",
                str((node.get("error") or {}).get("type", "-")) if node.get("error") else "-",
            ]
        )
    print("")
    print(ascii_table(["seq", "step", "status", "ms", "shape", "error"], rows))
    return 0


def _scan(path: str, recursive: bool) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if os.path.isfile(path):
        candidates = [path]
    elif os.path.isdir(path):
        candidates = []
        if recursive:
            for root_dir, _dirs, files in os.walk(path):
                for filename in sorted(files):
                    if filename.lower().endswith(".json"):
                        candidates.append(os.path.join(root_dir, filename))
        else:
            for filename in sorted(os.listdir(path)):
                full = os.path.join(path, filename)
                if filename.lower().endswith(".json") and os.path.isfile(full):
                    candidates.append(full)
    else:
        raise LineageError(f"path not found: {path}")
    for candidate in candidates:
        try:
            found.append((candidate, load_lineage(candidate)))
        except LineageError:
            continue
    return found


def cmd_list(args: argparse.Namespace) -> int:
    found = _scan(args.path, args.recursive)
    if args.json:
        payload = [
            {
                "file": os.path.abspath(path),
                "name": data.get("name"),
                "run_id": data.get("run_id"),
                "status": data.get("status"),
                "nodes": len(data.get("nodes") or []),
            }
            for path, data in found
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not found:
        print(f"no lineage files under {os.path.abspath(args.path)}")
        return 0
    rows = []
    for path, data in found:
        nodes = data.get("nodes") or []
        failed = sum(1 for node in nodes if isinstance(node, dict) and node.get("status") == "failed")
        rows.append(
            [
                str(data.get("name")),
                str(data.get("status")),
                str(len(nodes)),
                str(failed),
                str(data.get("run_id")),
                os.path.basename(path),
            ]
        )
    print(ascii_table(["name", "status", "nodes", "failed", "run_id", "file"], rows))
    return 0


def _task_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()] or ["analytics"]


def cmd_catalog(args: argparse.Namespace) -> int:
    tasks = _task_list(args.tasks)
    entries = collect_entries(args.path, license=args.license, tasks=tasks)
    if not entries:
        print(f"error: no lineage files under {os.path.abspath(args.path)}", file=sys.stderr)
        return 1
    for entry in entries:
        if args.version:
            entry["version"] = args.version
    catalog = build_catalog(entries)
    target = write_catalog(args.out, catalog)
    written_cards: list[str] = []
    if args.cards_dir:
        for entry in entries:
            written_cards.append(write_card(args.cards_dir, entry))
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
    else:
        rows = [
            [
                str(entry.get("name")),
                str(entry.get("version")),
                f"{entry.get('rows')}x{entry.get('cols')}",
                str(entry.get("license")),
                str(entry.get("updated_at")),
            ]
            for entry in entries
        ]
        print(ascii_table(["name", "version", "shape", "license", "updated_at"], rows))
        print(f"catalog: {target}")
        for path in written_cards:
            print(f"card   : {path}")
    return 0


def cmd_card(args: argparse.Namespace) -> int:
    data = _load(args.path)
    entry = make_entry(
        data,
        name=args.name,
        version=args.version,
        license=args.license,
        tasks=_task_list(args.tasks),
    )
    text = card_markdown(entry)
    if args.out:
        path = save_text(args.out, text)
        print(f"wrote {path}")
    else:
        print(text.rstrip())
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造 argparse 解析器（子命令 render/diff/show/list/catalog/card）。"""
    parser = argparse.ArgumentParser(
        prog="lineage",
        description="Zero-dependency lineage tracking for dataset pipelines.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"lineage {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="{render,diff,show,list,catalog,card}")

    render_parser = subparsers.add_parser("render", help="render a lineage json")
    render_parser.add_argument("path", help="lineage json file")
    render_parser.add_argument(
        "--format", "-f", choices=["mermaid", "dot", "tree"], default="tree",
        help="output format (default: tree)",
    )
    render_parser.add_argument("--out", "-o", help="write to a file instead of stdout")
    render_parser.set_defaults(func=cmd_render)

    diff_parser = subparsers.add_parser("diff", help="compare two lineage json files")
    diff_parser.add_argument("before", help="baseline lineage json")
    diff_parser.add_argument("after", help="candidate lineage json")
    diff_parser.add_argument("--json", action="store_true", help="print json instead of a table")
    diff_parser.add_argument("--out", "-o", help="write to a file instead of stdout")
    diff_parser.set_defaults(func=cmd_diff)

    show_parser = subparsers.add_parser("show", help="show run summary or one node")
    show_parser.add_argument("path", help="lineage json file")
    show_parser.add_argument("--node", help="node id or step name")
    show_parser.add_argument("--json", action="store_true", help="print the whole run as json")
    show_parser.set_defaults(func=cmd_show)

    list_parser = subparsers.add_parser("list", help="list lineage files under a directory")
    list_parser.add_argument("path", nargs="?", default=".", help="file or directory (default: .)")
    list_parser.add_argument("--json", action="store_true", help="print json instead of a table")
    list_parser.add_argument("--recursive", "-r", action="store_true", help="scan subdirectories")
    list_parser.set_defaults(func=cmd_list)

    catalog_parser = subparsers.add_parser("catalog", help="aggregate runs into catalog.json")
    catalog_parser.add_argument("path", help="directory with lineage json files")
    catalog_parser.add_argument("--out", "-o", default=os.path.join("artifacts", "catalog.json"))
    catalog_parser.add_argument("--cards-dir", help="also write dataset cards into this directory")
    catalog_parser.add_argument("--license", default=DEFAULT_LICENSE)
    catalog_parser.add_argument("--tasks", default="analytics", help="comma separated task list")
    catalog_parser.add_argument("--version", default="1.0.0", help="version for every entry")
    catalog_parser.add_argument("--json", action="store_true", help="print catalog json")
    catalog_parser.set_defaults(func=cmd_catalog)

    card_parser = subparsers.add_parser("card", help="render a dataset card markdown")
    card_parser.add_argument("path", help="lineage json file")
    card_parser.add_argument("--name", help="dataset name (default: run name)")
    card_parser.add_argument("--version", default="1.0.0")
    card_parser.add_argument("--license", default=DEFAULT_LICENSE)
    card_parser.add_argument("--tasks", default="analytics", help="comma separated task list")
    card_parser.add_argument("--out", "-o", help="write markdown to a file")
    card_parser.set_defaults(func=cmd_card)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口，返回退出码（0/1/2）。"""
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except LineageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
