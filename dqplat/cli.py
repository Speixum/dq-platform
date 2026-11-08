"""dqplat 命令行入口：run / list / show / validate。

退出码：0 成功，1 运行失败，2 用法或配置错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, find_pipeline_file, load_pipeline
from .contracts import validate_file
from .runner import Runner, summarize


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve() if getattr(args, "root", None) else Path(__file__).resolve().parent.parent


def _load(path_text: str, root: Path):
    target = find_pipeline_file(path_text, root)
    return load_pipeline(target), target


def cmd_run(args: argparse.Namespace) -> int:
    root = _root(args)
    try:
        pipeline, target = _load(args.pipeline, root)
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2

    runner = Runner(
        pipeline,
        root,
        run_dir=args.run_dir,
        override_timeout=args.timeout,
        only=_split(args.only) if args.only else (),
        skip=_split(args.skip) if args.skip else (),
        dry_run=args.dry_run,
        resume=args.resume,
        quiet=args.quiet and not args.json,
    )
    print(f"pipeline: {pipeline.name} {pipeline.version} ({target.name})")
    print(f"run dir : {runner.run_dir}")
    manifest = runner.execute()
    if not args.quiet:
        print()
        print(summarize(manifest))
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not args.dry_run:
        print(f"manifest: {runner.run_dir / 'manifest.json'}")
    return 0 if manifest["status"] in ("ok", "dry-run") else 1


def cmd_list(args: argparse.Namespace) -> int:
    root = _root(args)
    try:
        pipeline, target = _load(args.pipeline, root)
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2
    print(f"{pipeline.name} {pipeline.version}  ({target})")
    if pipeline.description:
        print(pipeline.description)
    print()
    rows = [["STEP", "CWD", "REQUIRES", "OPTIONAL"]]
    for step in pipeline.steps:
        rows.append([
            step.id,
            step.cwd,
            str(len(step.requires)),
            "yes" if step.optional else "no",
        ])
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for index, row in enumerate(rows):
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if index == 0:
            print("  ".join("-" * width for width in widths))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    target = Path(args.run_dir) / "manifest.json"
    if not target.is_file():
        target = Path(args.run_dir)
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read manifest: {exc}")
        return 2
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    print(f"pipeline: {manifest.get('pipeline', {}).get('name')} {manifest.get('pipeline', {}).get('version')}")
    print(f"status  : {manifest.get('status')}")
    print(f"started : {manifest.get('started_at')}  finished: {manifest.get('finished_at')}")
    print()
    print(summarize(manifest))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    failed = 0
    for raw in args.paths:
        path = Path(raw)
        problems = validate_file(path)
        if problems:
            failed += 1
            print(f"[bad ] {path}")
            for problem in problems:
                print(f"       - {problem}")
        else:
            print(f"[ok  ] {path}")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dqplat", description="orchestrate the six data-tool repos (stdlib only)")
    parser.add_argument("--version", action="version", version=f"dqplat {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="execute a pipeline")
    run.add_argument("pipeline", help="pipeline name under pipelines/ or a .toml path")
    run.add_argument("--root", help="repository root (default: parent of the dqplat package)")
    run.add_argument("--run-dir", help="write artifacts here instead of artifacts/runs/<stamp>")
    run.add_argument("--timeout", type=int, help="override every step timeout (seconds)")
    run.add_argument("--dry-run", action="store_true", help="print the resolved commands, run nothing")
    run.add_argument("--resume", help="reuse unchanged steps from a previous run directory")
    run.add_argument("--only", help="comma separated step ids to run")
    run.add_argument("--skip", help="comma separated step ids to skip")
    run.add_argument("--quiet", action="store_true", help="only print errors")
    run.add_argument("--json", action="store_true", help="print the manifest as JSON")
    run.set_defaults(func=cmd_run)

    listing = sub.add_parser("list", help="show the steps of a pipeline")
    listing.add_argument("pipeline", help="pipeline name under pipelines/ or a .toml path")
    listing.add_argument("--root", help="repository root")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="summarise a finished run")
    show.add_argument("run_dir", help="run directory (or a manifest.json path)")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    validate = sub.add_parser("validate", help="check artifacts against the shared JSON contracts")
    validate.add_argument("paths", nargs="+", help="JSON artifacts (pii / lineage / report)")
    validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
