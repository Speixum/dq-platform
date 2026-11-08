"""dqplat: 六个数据工具仓库的编排层（只依赖标准库）。

设计约束：
- 不 import vendor/ 下的任何模块，只通过子进程调用各仓库自带的 CLI；
- 只读写显式给出的路径，不联网、不写注册表；
- 每步产物落 artifacts/runs/<时间戳>/，并登记 sha256 到 manifest.json。
"""

from __future__ import annotations

__all__ = ["__version__", "RUN_SCHEMA"]

__version__ = "0.1.0"

#: 运行清单（manifest.json）的 schema 标识。
RUN_SCHEMA = "dq-run/1.0"
