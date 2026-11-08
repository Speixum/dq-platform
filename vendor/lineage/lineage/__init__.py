"""data-lineage-lite：零依赖的数据集生产链路血缘追踪库。

公开 API：
- ``track`` / ``run``：步骤血缘记录；
- ``hash_file`` / ``hash_table`` / ``fingerprint_object``：内容哈希；
- ``profile_table``：表格质量指纹；
- ``make_entry`` / ``build_catalog`` / ``card_markdown``：数据集卡片与 catalog；
- ``to_mermaid`` / ``to_dot`` / ``to_tree``：血缘渲染；
- ``diff_runs``：两次 run 的节点级比较。
"""

from __future__ import annotations

from .catalog import (
    CATALOG_SCHEMA,
    build_catalog,
    card_markdown,
    dataset_from_run,
    load_catalog,
    make_entry,
    write_card,
    write_catalog,
)
from .diff import DIFF_SCHEMA, diff_runs
from .errors import LineageError, LineageFormatError
from .hashing import (
    hash_file,
    hash_json,
    hash_table,
    is_dataframe,
    is_table,
    json_snapshot,
    sha256_bytes,
    unstable_hash,
)
from .io import load_json, load_lineage, save_json, save_text
from .profile import profile_table
from .render import to_dot, to_mermaid, to_tree
from .tracker import Run, active_run, run, track, utc_now

__version__ = "0.1.0"

__all__ = [
    "CATALOG_SCHEMA",
    "DIFF_SCHEMA",
    "LineageError",
    "LineageFormatError",
    "Run",
    "active_run",
    "build_catalog",
    "card_markdown",
    "dataset_from_run",
    "diff_runs",
    "hash_file",
    "hash_json",
    "hash_table",
    "is_dataframe",
    "is_table",
    "json_snapshot",
    "load_catalog",
    "load_json",
    "load_lineage",
    "make_entry",
    "profile_table",
    "run",
    "save_json",
    "save_text",
    "sha256_bytes",
    "to_dot",
    "to_mermaid",
    "to_tree",
    "track",
    "unstable_hash",
    "utc_now",
    "write_card",
    "write_catalog",
    "__version__",
]
