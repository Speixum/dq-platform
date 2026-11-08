"""流水线配置：把 pipelines/*.toml 解析成 Step / Pipeline。

占位符（在 runner 里替换，不在配置里拼绝对路径）：
    {root}    仓库根目录
    {out}     本次运行目录 artifacts/runs/<stamp>
    {python}  当前解释器（sys.executable）
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """配置不合法：字段缺失、类型错误或步骤 id 重复。"""


@dataclass(frozen=True)
class Step:
    """一个可执行步骤。"""

    id: str
    command: tuple[str, ...]
    cwd: str = "."
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    timeout: int = 600
    optional: bool = True
    continue_on_error: bool = False
    note: str = ""


@dataclass(frozen=True)
class Pipeline:
    """一条有序步骤链。"""

    name: str
    version: str
    description: str
    steps: tuple[Step, ...]

    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.id for step in self.steps)


def _as_str_tuple(value: object, key: str, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where}: '{key}' must be a list of strings")
    return tuple(value)


def _parse_step(raw: dict, index: int, seen: set[str]) -> Step:
    where = f"step#{index + 1}"
    step_id = raw.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        raise ConfigError(f"{where}: 'id' must be a non-empty string")
    where = f"step '{step_id}'"
    if step_id in seen:
        raise ConfigError(f"{where}: duplicate id")
    seen.add(step_id)

    command = raw.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise ConfigError(f"{where}: 'command' must be a non-empty list of strings")

    cwd = raw.get("cwd", ".")
    if not isinstance(cwd, str):
        raise ConfigError(f"{where}: 'cwd' must be a string")

    timeout = raw.get("timeout", 600)
    if not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError(f"{where}: 'timeout' must be a positive integer")

    return Step(
        id=step_id,
        command=tuple(command),
        cwd=cwd,
        requires=_as_str_tuple(raw.get("requires"), "requires", where),
        produces=_as_str_tuple(raw.get("produces"), "produces", where),
        timeout=timeout,
        optional=bool(raw.get("optional", True)),
        continue_on_error=bool(raw.get("continue_on_error", False)),
        note=str(raw.get("note", "")),
    )


def load_pipeline(path: str | Path) -> Pipeline:
    """读取并校验一份流水线 TOML。"""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"pipeline not found: {target}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {target}: {exc}") from exc

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{target}: 'name' must be a non-empty string")
    version = data.get("version", "1.0")
    description = data.get("description", "")
    if not isinstance(version, str) or not isinstance(description, str):
        raise ConfigError(f"{target}: 'version' and 'description' must be strings")

    raw_steps = data.get("step")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ConfigError(f"{target}: needs at least one [[step]]")

    seen: set[str] = set()
    steps = tuple(
        _parse_step(raw, index, seen)
        for index, raw in enumerate(raw_steps)
        if isinstance(raw, dict) or _raise_step_type(target, index)
    )
    return Pipeline(name=name.strip(), version=version, description=description, steps=steps)


def _raise_step_type(path: Path, index: int):
    raise ConfigError(f"{path}: step#{index + 1} must be a table")


def find_pipeline_file(name_or_path: str, root: Path) -> Path:
    """按路径或名字定位流水线文件（名字会在 pipelines/ 下找）。"""
    candidate = Path(name_or_path)
    if candidate.exists():
        return candidate
    if not candidate.suffix:
        candidate = root / "pipelines" / f"{name_or_path}.toml"
    return candidate
