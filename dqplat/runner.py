"""执行器：按顺序调用各仓库 CLI，把每次运行落成 artifacts/runs/<stamp>/。

每一次运行产出一份 manifest.json（dq-run/1.0），包含：
- 流水线名/版本、解释器版本、起止时间、总体状态；
- 每个步骤的命令、cwd、退出码、耗时、日志路径；
- 每个产物的相对路径、字节数、sha256。

只依赖标准库；不 import vendor/ 下的任何模块。
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import RUN_SCHEMA, __version__
from .config import Pipeline, Step

LOG_DIR = "logs"
MANIFEST_NAME = "manifest.json"

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"
DRY_RUN = "dry-run"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expand(pattern: str) -> str:
    return pattern.replace("\\", "/")


@dataclass
class StepResult:
    step: Step
    status: str
    exit_code: int | None = None
    duration_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    command: list[str] | None = None
    cwd: str = ""
    log: str = ""
    reason: str = ""
    produces: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.step.id,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 1),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "command": self.command or list(self.step.command),
            "cwd": self.cwd,
            "log": self.log,
            "reason": self.reason,
            "produces": self.produces or [],
            "note": self.step.note,
        }


class Runner:
    """执行一条流水线。"""

    def __init__(
        self,
        pipeline: Pipeline,
        root: str | Path,
        *,
        run_dir: str | Path | None = None,
        override_timeout: int | None = None,
        only: tuple[str, ...] = (),
        skip: tuple[str, ...] = (),
        dry_run: bool = False,
        resume: str | Path | None = None,
        quiet: bool = False,
    ) -> None:
        self.pipeline = pipeline
        self.root = Path(root).resolve()
        self.run_dir = Path(run_dir).resolve() if run_dir else self.root / "artifacts" / "runs" / utc_stamp()
        self.override_timeout = override_timeout
        self.only = set(only)
        self.skip = set(skip)
        self.dry_run = dry_run
        self.quiet = quiet
        self._seen: dict[str, dict[str, Any]] = {}
        if resume is not None:
            self._seen = self._load_previous(Path(resume))

    # ---- 内部工具 -------------------------------------------------
    def _load_previous(self, path: Path) -> dict[str, dict[str, Any]]:
        target = path / MANIFEST_NAME if path.is_dir() else path
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._log(f"[warn] resume ignored: {exc}")
            return {}
        steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(steps, list):
            return {}
        kept: dict[str, dict[str, Any]] = {}
        for item in steps:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            if item.get("status") == OK:
                kept[item["id"]] = item
        return kept

    def _log(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    def _resolve(self, text: str) -> str:
        return (
            text.replace("{root}", str(self.root))
            .replace("{out}", str(self.run_dir))
            .replace("{python}", sys.executable)
        )

    def _step_paths(self, step: Step, kind: str) -> list[Path]:
        items = step.requires if kind == "requires" else step.produces
        paths: list[Path] = []
        for item in items:
            raw = self._resolve(item)
            candidate = Path(raw)
            if not candidate.is_absolute():
                base = self.root / step.cwd
                candidate = base / candidate
            paths.append(candidate)
        return paths

    def _missing_requires(self, step: Step) -> list[str]:
        missing: list[str] = []
        for path in self._step_paths(step, "requires"):
            if not path.exists():
                try:
                    shown = path.relative_to(self.root)
                except ValueError:
                    shown = path
                missing.append(str(shown).replace("\\", "/"))
        return missing

    def _collect_produces(self, step: Step) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self._step_paths(step, "produces"):
            matches = sorted(path.parent.glob(path.name)) if any(ch in path.name for ch in "*?[") else [path]
            for match in matches:
                if not match.is_file():
                    continue
                try:
                    shown = match.relative_to(self.root)
                except ValueError:
                    shown = match
                out.append(
                    {
                        "path": str(shown).replace("\\", "/"),
                        "bytes": match.stat().st_size,
                        "sha256": sha256_file(match),
                    }
                )
        return out

    def _resume_ok(self, step: Step) -> bool:
        previous = self._seen.get(step.id)
        if not previous:
            return False
        if previous.get("command") != [self._resolve(item) for item in step.command]:
            return False
        recorded = previous.get("produces") or []
        if not recorded:
            return False
        for item in recorded:
            if not isinstance(item, dict):
                return False
            path = self.root / str(item.get("path"))
            if not path.is_file() or sha256_file(path) != item.get("sha256"):
                return False
        return True

    # ---- 主流程 ---------------------------------------------------
    def execute(self) -> dict[str, Any]:
        started_at = utc_now()
        if not self.dry_run:
            (self.run_dir / LOG_DIR).mkdir(parents=True, exist_ok=True)

        results: list[StepResult] = []
        overall = OK

        for step in self.pipeline.steps:
            if self.only and step.id not in self.only:
                results.append(StepResult(step=step, status=SKIPPED, reason="filtered by --only"))
                continue
            if step.id in self.skip:
                results.append(StepResult(step=step, status=SKIPPED, reason="filtered by --skip"))
                continue

            missing = self._missing_requires(step)
            if missing:
                detail = "missing: " + ", ".join(missing)
                if step.optional:
                    results.append(StepResult(step=step, status=SKIPPED, reason=detail))
                    self._log(f"[skip] {step.id}: {detail}")
                    continue
                results.append(StepResult(step=step, status=FAILED, reason=detail))
                self._log(f"[fail] {step.id}: {detail}")
                overall = FAILED
                break

            if self._resume_ok(step):
                results.append(StepResult(step=step, status=SKIPPED, reason="resumed from previous run"))
                self._log(f"[reuse] {step.id}: unchanged artifacts")
                continue

            if self.dry_run:
                result = StepResult(
                    step=step,
                    status=DRY_RUN,
                    command=[self._resolve(item) for item in step.command],
                    cwd=str((self.root / step.cwd)),
                )
                results.append(result)
                self._log(f"[plan] {step.id}: {' '.join(result.command or [])}")
                continue

            result = self._run_step(step)
            results.append(result)
            if result.status == FAILED and not step.continue_on_error:
                overall = FAILED
                break

        finished_at = utc_now()
        if overall == OK and any(item.status == FAILED for item in results):
            overall = FAILED

        manifest = {
            "schema": RUN_SCHEMA,
            "tool": {"name": "dqplat", "version": __version__},
            "pipeline": {"name": self.pipeline.name, "version": self.pipeline.version},
            "status": overall if not self.dry_run else DRY_RUN,
            "started_at": started_at,
            "finished_at": finished_at,
            "python": platform.python_version(),
            "platform": sys.platform,
            "root": str(self.root),
            "run_dir": str(self.run_dir),
            "steps": [item.to_dict() for item in results],
        }
        if not self.dry_run:
            self._write_manifest(manifest)
        return manifest

    def _prepare_outputs(self, step: Step) -> None:
        """为声明过的产物预建父目录，避免 CLI 因为目录不存在而失败。"""
        for path in self._step_paths(step, "produces"):
            path.parent.mkdir(parents=True, exist_ok=True)

    def _run_step(self, step: Step) -> StepResult:
        self._prepare_outputs(step)
        command = [self._resolve(item) for item in step.command]
        cwd = (self.root / step.cwd).resolve()
        timeout = self.override_timeout or step.timeout
        started_at = utc_now()
        log_path = self.run_dir / LOG_DIR / f"{step.id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        clock = time.perf_counter()
        self._log(f"[run ] {step.id}: {' '.join(command)}")
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            code = completed.returncode
            stdout, stderr = completed.stdout or "", completed.stderr or ""
        except FileNotFoundError as exc:
            elapsed = (time.perf_counter() - clock) * 1000
            log_path.write_text(f"command not found: {exc}\n", encoding="utf-8")
            return StepResult(
                step=step, status=FAILED, exit_code=None, duration_ms=elapsed,
                started_at=started_at, finished_at=utc_now(), command=command,
                cwd=str(cwd), log=str(log_path.relative_to(self.root)).replace("\\", "/"),
                reason=f"command not found: {command[0]}",
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - clock) * 1000
            log_path.write_text(f"timeout after {timeout}s: {' '.join(command)}\n", encoding="utf-8")
            return StepResult(
                step=step, status=FAILED, exit_code=None, duration_ms=elapsed,
                started_at=started_at, finished_at=utc_now(), command=command,
                cwd=str(cwd), log=str(log_path.relative_to(self.root)).replace("\\", "/"),
                reason=f"timeout after {timeout}s",
            )

        elapsed = (time.perf_counter() - clock) * 1000
        log_path.write_text(
            "$ " + " ".join(command) + "\n\n--- stdout ---\n" + stdout + "\n--- stderr ---\n" + stderr,
            encoding="utf-8",
        )
        status = OK if code == 0 else FAILED
        produces = self._collect_produces(step)
        tail = (stdout or stderr).strip().splitlines()
        if tail:
            self._log("       " + tail[-1][:160])
        self._log(f"[{status}] {step.id} ({elapsed / 1000:.2f}s, exit={code})")
        return StepResult(
            step=step,
            status=status,
            exit_code=code,
            duration_ms=elapsed,
            started_at=started_at,
            finished_at=utc_now(),
            command=command,
            cwd=str(cwd),
            log=str(log_path.relative_to(self.root)).replace("\\", "/"),
            reason="" if status == OK else f"exit code {code}",
            produces=produces,
        )

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        target = self.run_dir / MANIFEST_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(manifest: dict[str, Any]) -> str:
    """把 manifest 压成一张 ASCII 表格。"""
    rows = [["STEP", "STATUS", "TIME", "DETAIL"]]
    for item in manifest.get("steps") or []:
        detail = item.get("reason") or ""
        if not detail and item.get("produces"):
            detail = f"{len(item['produces'])} file(s)"
        rows.append([
            str(item.get("id", "")),
            str(item.get("status", "")),
            f"{float(item.get('duration_ms') or 0) / 1000:.2f}s",
            detail[:56],
        ])
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)
