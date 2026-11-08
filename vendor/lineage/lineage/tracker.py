"""步骤血缘追踪：``track`` 装饰器与 ``run`` 上下文管理器。

设计要点：
- 活动 run 存在 contextvars 里，天然按线程/协程隔离；节点追加用 RLock 保护；
- 节点 id 形如 ``{run}/{step}#{seq}``，seq 在各自 run 作用域内自增（两位补零）；
- 没有活动 run 时装饰器直接透传，不影响原有调用；
- 步骤抛异常时先把失败节点写入血缘，再把异常原样抛出（不吞异常）。
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import platform
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, TypeVar

from .hashing import fingerprint_object, json_snapshot
from .io import save_json

SCHEMA = "dataset-lineage/1.0"
_CWD_PLACEHOLDER = "."

F = TypeVar("F", bound=Callable[..., Any])

_current: contextvars.ContextVar["Run | None"] = contextvars.ContextVar(
    "lineage_current_run", default=None
)


def utc_now() -> str:
    """当前 UTC 时间的 ISO 8601 字符串，形如 ``2026-11-08T01:35:00Z``。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    """用于 run_id 的紧凑 UTC 时间戳，形如 ``20261108T013500Z``。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class _Store:
    """一次根 run 内共享的节点/边容器（加锁，线程安全）。"""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.lock = threading.RLock()
        self._seq: dict[str, int] = {}
        self._last: dict[str, str] = {}

    def next_seq(self, scope: str) -> int:
        """在指定 run 作用域内取下一个序号。"""
        with self.lock:
            value = self._seq.get(scope, 0) + 1
            self._seq[scope] = value
            return value

    def append(self, scope: str, node: dict[str, Any], label: str) -> None:
        """追加节点，并在同一作用域内自动连出上一条边。"""
        with self.lock:
            previous = self._last.get(scope)
            self.nodes.append(node)
            self._last[scope] = node["id"]
            if previous is not None:
                self.edges.append({"from": previous, "to": node["id"], "label": label})


def _error_payload(exc: BaseException) -> dict[str, Any]:
    """把异常转成可序列化的 ``{type, message, traceback}``。"""
    try:
        message = str(exc)
    except Exception:  # pragma: no cover
        message = f"<{type(exc).__name__}>"
    lines = [
        line.rstrip()
        for line in "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).splitlines()
    ]
    return {"type": type(exc).__name__, "message": message, "traceback": lines}


def _edge_label(inputs: list[dict[str, Any]]) -> str:
    """边标签取第一个输入的 kind，无输入时为 flow。"""
    if not inputs:
        return "flow"
    kind = inputs[0].get("kind")
    return str(kind) if isinstance(kind, str) else "flow"


class Run:
    """一次 run 的句柄：可序列化为 ``dataset-lineage/1.0`` JSON。"""

    def __init__(self, name: str, store: "_Store | None" = None, parent: "Run | None" = None) -> None:
        self.name = name
        self.parent = parent
        self.started_at = utc_now()
        self.finished_at: str | None = None
        self.status = "running"
        self.sealed = False
        self._store = store if store is not None else _Store()
        self.run_id = f"{name.replace('/', '-')}-{utc_stamp()}"

    # -- 记录 ---------------------------------------------------------
    def record(self, node: dict[str, Any], label: str = "flow") -> None:
        """登记一个外部构造的节点（供高级用法使用）。"""
        self._store.append(self.name, node, label)

    def next_seq(self) -> int:
        """当前作用域的下一个序号。"""
        return self._store.next_seq(self.name)

    # -- 封口 ---------------------------------------------------------
    def _finish(self, exc: BaseException | None) -> None:
        if self.sealed:
            return
        self.finished_at = utc_now()
        self.status = "failed" if exc is not None else "ok"
        self.sealed = True

    # -- 序列化 -------------------------------------------------------
    def _nodes(self) -> list[dict[str, Any]]:
        prefix = self.name + "/"
        with self._store.lock:
            return [node for node in self._store.nodes if str(node.get("id", "")).startswith(prefix)]

    def _edges(self) -> list[dict[str, Any]]:
        allowed = {node["id"] for node in self._nodes()}
        with self._store.lock:
            return [
                edge
                for edge in self._store.edges
                if edge.get("from") in allowed and edge.get("to") in allowed
            ]

    def to_dict(self) -> dict[str, Any]:
        """导出为契约 3.1 的血缘 dict。"""
        return {
            "schema": SCHEMA,
            "run_id": self.run_id,
            "name": self.name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "env": {
                "python": platform.python_version(),
                "platform": sys.platform,
                "cwd": _CWD_PLACEHOLDER,
            },
            "nodes": self._nodes(),
            "edges": self._edges(),
        }

    def to_json(self, *, indent: int = 2) -> str:
        """导出为 JSON 文本（不转义中文）。"""
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save(self, path: str) -> str:
        """把血缘写入 JSON 文件，返回绝对路径。"""
        return save_json(path, self.to_dict())

    def summary(self) -> dict[str, Any]:
        """轻量摘要：节点数、失败数、总耗时。"""
        nodes = self._nodes()
        failed = [node for node in nodes if node.get("status") == "failed"]
        total = sum(float(node.get("duration_ms") or 0.0) for node in nodes)
        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "nodes": len(nodes),
            "failed": len(failed),
            "duration_ms": round(total, 3),
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Run {self.name} status={self.status} nodes={len(self._nodes())}>"


@contextmanager
def run(name: str) -> Iterator[Run]:
    """开启一次血缘 run；退出时封口（记录 finished_at 与 status），异常不吞。

    嵌套调用会在当前 run 下开启子作用域：子 run 的名字变成 ``父run/子run``，
    节点 id 因此带上父前缀，父 run 的血缘里能看到子步骤，异常照常向上传播。
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("run name must be a non-empty string")
    parent = _current.get()
    scope = name if parent is None else f"{parent.name}/{name}"
    current = Run(
        scope,
        store=parent._store if parent is not None else None,
        parent=parent,
    )
    token = _current.set(current)
    try:
        yield current
    except BaseException as exc:
        current._finish(exc)
        raise
    else:
        current._finish(None)
    finally:
        _current.reset(token)


def active_run() -> Run | None:
    """返回当前上下文中的活动 run（没有则返回 None）。"""
    return _current.get()


def _bind(signature: "inspect.Signature | None", args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """按签名把实参绑定成 {参数名: 值}，剔除 self/cls。"""
    skip = {"self", "cls"}
    if signature is not None:
        try:
            bound = signature.bind(*args, **kwargs)
        except TypeError:
            bound = None
        if bound is not None:
            return {
                name: value
                for name, value in bound.arguments.items()
                if name not in skip
            }
    fallback: dict[str, Any] = {f"arg{index}": value for index, value in enumerate(args)}
    fallback.update(kwargs)
    return {key: value for key, value in fallback.items() if key not in skip}


def _snapshot_params(bound: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """逐个参数做 JSON 快照，避免把参数映射整体误判成表格。"""
    snapshot: dict[str, Any] = {}
    unstable = False
    for name, value in bound.items():
        converted, item_unstable = json_snapshot(value)
        snapshot[name] = converted
        unstable = unstable or item_unstable
    return snapshot, unstable


def track(step: str) -> Callable[[F], F]:
    """装饰器：把一次函数调用记录为一个血缘节点。

    记录 params 的 JSON 快照、输入/输出哈希、耗时与状态；失败节点记录 error 后继续抛出异常。
    没有活动 run 时直接透传，不产生任何记录。
    """

    def decorator(func: F) -> F:
        try:
            signature: "inspect.Signature | None" = inspect.signature(func)
        except (TypeError, ValueError):  # pragma: no cover - 内建函数
            signature = None

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current = _current.get()
            if current is None:
                return func(*args, **kwargs)

            bound = _bind(signature, args, kwargs)
            params, params_unstable = _snapshot_params(bound)
            started_at = utc_now()
            clock = time.perf_counter()
            inputs = [
                fingerprint_object(value, ref=name) for name, value in bound.items()
            ]
            seq = current.next_seq()
            node: dict[str, Any] = {
                "id": f"{current.name}/{step}#{seq:02d}",
                "step": step,
                "seq": seq,
                "status": "ok",
                "started_at": started_at,
                "duration_ms": 0.0,
                "params": params,
                "inputs": inputs,
                "outputs": [],
                "error": None,
                "unstable": params_unstable or any(
                    bool(item.get("unstable")) for item in inputs
                ),
            }
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                node["status"] = "failed"
                node["duration_ms"] = round((time.perf_counter() - clock) * 1000, 3)
                node["error"] = _error_payload(exc)
                current.record(node, _edge_label(inputs))
                raise

            output = fingerprint_object(result)
            node["outputs"] = [output]
            node["duration_ms"] = round((time.perf_counter() - clock) * 1000, 3)
            if output.get("unstable"):
                node["unstable"] = True
            current.record(node, _edge_label(inputs))
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
