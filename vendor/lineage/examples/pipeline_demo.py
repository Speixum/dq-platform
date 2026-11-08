"""示例管线：ingest -> clean -> enrich -> validate -> publish，全部纯标准库。

用法：
    python examples/make_fixtures.py
    python examples/pipeline_demo.py              # 版本 1.0.0，写到 artifacts/lineage/demo.json
    python examples/pipeline_demo.py --variant b  # 参数变体，写到 demo_v2.json，用于演示 diff

产物（均被 .gitignore 排除）：
    artifacts/publish/demo_users-<version>.csv 与 .manifest.json
    artifacts/lineage/demo.json / demo.md（以及 demo_v2.json / demo_v2.md、demo_failed.json）
    artifacts/catalog.json 与 artifacts/cards/demo_users.md
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lineage
from lineage.catalog import build_catalog, load_catalog, make_entry, upsert, write_card, write_catalog
from lineage.hashing import hash_table
from lineage.io import save_json, save_text
from lineage.profile import profile_table
from lineage.render import to_tree

# 想验证 diff 就改这里：把 "median" 改成 "zero"，再跑一次管线并 diff 两次的 lineage。
FILL_STRATEGY = "median"
DROP_DUPLICATES = True
NORMALISE_CITY = True

DATASET_NAME = "demo_users"
LICENSE = "CC-BY-4.0"
TASKS = ["analytics", "profiling", "quality-monitoring"]

REQUIRED_COLUMNS = ("user_id", "name", "city", "age", "signup_date", "amount", "status")
STATUS_VALUES = ("active", "inactive", "pending")
AGE_RANGE = (0, 110)
SIGNUP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CITY_ALIASES = {
    "beijing": "Beijing",
    "shanghai": "Shanghai",
    "shenzhen": "Shenzhen",
    "hangzhou": "Hangzhou",
    "chengdu": "Chengdu",
    "wuhan": "Wuhan",
}

DEFAULT_RAW = ROOT / "examples" / "data" / "raw_users.csv"
DEFAULT_ARTIFACTS = ROOT / "artifacts"


def _to_number(value: Any) -> float | None:
    """把单元格转成数字；缺失与噪声文本返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"n/a", "na", "null", "none", "unknown", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _median(values: list[float]) -> float | None:
    """中位数（只用排序与下标，不引入额外依赖）。"""
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _fill_value(values: list[float], strategy: str) -> float:
    """按策略给出缺失值填充值：median 或 zero。"""
    if strategy == "zero":
        return 0.0
    median = _median(values)
    return 0.0 if median is None else median


def _age_band(age: float) -> str:
    """年龄分桶（演示 enrich 的派生字段）。"""
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    return "55+"


def _segment(amount: float) -> str:
    """金额分档（演示 enrich 的派生字段）。"""
    if amount < 100:
        return "low"
    if amount < 500:
        return "mid"
    return "high"


@lineage.track("ingest")
def ingest(path: str) -> list[dict[str, Any]]:
    """读取原始 CSV，返回行字典列表（列序按表头）。"""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError("input csv has no data rows")
    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise ValueError("input csv misses columns: " + ", ".join(missing))
    return rows


@lineage.track("clean")
def clean(
    rows: list[dict[str, Any]],
    fill_strategy: str = FILL_STRATEGY,
    drop_duplicates: bool = DROP_DUPLICATES,
) -> list[dict[str, Any]]:
    """清洗：去空白、把噪声文本转成缺失、按策略填充、按 user_id 去重。"""
    prepared: list[dict[str, Any]] = []
    for row in rows:
        prepared.append(
            {
                "user_id": str(row.get("user_id") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "city": str(row.get("city") or "").strip(),
                "age": _to_number(row.get("age")),
                "signup_date": str(row.get("signup_date") or "").strip(),
                "amount": _to_number(row.get("amount")),
                "status": str(row.get("status") or "").strip().lower(),
            }
        )

    age_fill = _fill_value(
        [row["age"] for row in prepared if row["age"] is not None], fill_strategy
    )
    amount_fill = _fill_value(
        [row["amount"] for row in prepared if row["amount"] is not None], fill_strategy
    )
    for row in prepared:
        if row["age"] is None:
            row["age"] = age_fill
        if row["amount"] is None:
            row["amount"] = amount_fill

    if not drop_duplicates:
        return prepared
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in prepared:
        key = row["user_id"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


@lineage.track("enrich")
def enrich(
    rows: list[dict[str, Any]],
    normalise_city: bool = NORMALISE_CITY,
) -> list[dict[str, Any]]:
    """派生字段：age_band、segment、signup_month；可选城市名规范化。"""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["age_band"] = _age_band(float(row["age"]))
        item["segment"] = _segment(float(row["amount"]))
        item["signup_month"] = str(row["signup_date"])[:7]
        if normalise_city:
            item["city"] = CITY_ALIASES.get(
                str(row.get("city") or "").strip().lower(), row.get("city")
            )
        enriched.append(item)
    return enriched


@lineage.track("validate")
def validate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """校验必填/范围/唯一性；发现问题时抛 ValueError（演示失败节点）。"""
    problems: list[str] = []
    seen_ids: set[str] = set()
    for position, row in enumerate(rows, start=1):
        user_id = str(row.get("user_id") or "")
        if not user_id:
            problems.append(f"row {position}: empty user_id")
        elif user_id in seen_ids:
            problems.append(f"row {position}: duplicated user_id {user_id}")
        else:
            seen_ids.add(user_id)
        if not str(row.get("name") or "").strip():
            problems.append(f"row {position}: empty name")
        age = row.get("age")
        if age is None:
            problems.append(f"row {position}: missing age")
        elif not (AGE_RANGE[0] <= float(age) <= AGE_RANGE[1]):
            problems.append(f"row {position}: age out of range: {age}")
        amount = row.get("amount")
        if amount is None:
            problems.append(f"row {position}: missing amount")
        elif float(amount) < 0:
            problems.append(f"row {position}: negative amount: {amount}")
        if str(row.get("status") or "") not in STATUS_VALUES:
            problems.append(f"row {position}: unexpected status: {row.get('status')}")
        signup = str(row.get("signup_date") or "")
        if not SIGNUP_RE.match(signup):
            problems.append(f"row {position}: bad signup_date: {signup}")
        else:
            try:
                date.fromisoformat(signup)
            except ValueError:
                problems.append(f"row {position}: invalid signup_date: {signup}")
    if problems:
        raise ValueError(f"validation failed: {len(problems)} problems, first={problems[0]}")
    return {"rows": len(rows), "columns": len(rows[0]) if rows else 0, "problems": 0}


@lineage.track("publish")
def publish(
    rows: list[dict[str, Any]],
    name: str = DATASET_NAME,
    version: str = "1.0.0",
    directory: str = str(DEFAULT_ARTIFACTS / "publish"),
) -> list[dict[str, Any]]:
    """写出 CSV 与 manifest（真实入库清单），返回行数据供 catalog 取表格指纹。"""
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    profile = profile_table(rows)
    columns = list(profile["columns"])
    csv_path = target_dir / f"{name}-{version}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})
    manifest = {
        "schema": "publish-manifest/1.0",
        "dataset": name,
        "version": version,
        "rows": len(rows),
        "columns": columns,
        "content_hash": hash_table(rows),
        "profile": profile,
        "files": [csv_path.name],
    }
    save_json(target_dir / f"{name}-{version}.manifest.json", manifest)
    return rows


def run_pipeline(
    run_name: str,
    version: str,
    raw_csv: Path,
    artifacts: Path,
    fill_strategy: str = FILL_STRATEGY,
    drop_duplicates: bool = DROP_DUPLICATES,
    normalise_city: bool = NORMALISE_CITY,
) -> lineage.Run:
    """执行五步管线，返回已封口的 run 句柄。"""
    publish_dir = artifacts / "publish"
    with lineage.run(run_name) as current:
        raw = ingest(str(raw_csv))
        cleaned = clean(raw, fill_strategy=fill_strategy, drop_duplicates=drop_duplicates)
        enriched = enrich(cleaned, normalise_city=normalise_city)
        validate(enriched)
        publish(enriched, name=DATASET_NAME, version=version, directory=str(publish_dir))
    return current


def write_report(path: Path, current: lineage.Run, version: str) -> Path:
    """把 run 渲染成 markdown 报告（含 ASCII 步骤树与节点明细表）。"""
    data = current.to_dict()
    nodes = data["nodes"]
    lines = [
        f"# 血缘报告：{data['name']}",
        "",
        f"- run_id：{data['run_id']}",
        f"- 状态：{data['status']}",
        f"- 时间窗：{data['started_at']} -> {data['finished_at']}",
        f"- 数据集版本：{version}",
        f"- 节点数：{len(nodes)}",
        "",
        "## 步骤树",
        "",
        "```text",
        to_tree(data).rstrip(),
        "```",
        "",
        "## 节点明细",
        "",
        "| seq | step | status | duration_ms | rows | null_ratio |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for node in nodes:
        fingerprint: dict[str, Any] = {}
        for output in node.get("outputs") or []:
            if isinstance(output, dict) and isinstance(output.get("fingerprint"), dict):
                fingerprint = output["fingerprint"]
                break
        lines.append(
            "| {seq:02d} | {step} | {status} | {duration} | {rows} | {nulls} |".format(
                seq=int(node.get("seq") or 0),
                step=node.get("step"),
                status=node.get("status"),
                duration=node.get("duration_ms"),
                rows=fingerprint.get("rows", "-"),
                nulls=fingerprint.get("null_ratio", "-"),
            )
        )
    lines.append("")
    return Path(save_text(str(path), "\n".join(lines)))


def update_catalog(artifacts: Path, current: lineage.Run, version: str) -> tuple[Path, Path]:
    """把本次 run 汇总进 catalog.json，并刷新数据集卡片。"""
    entry = make_entry(
        current.to_dict(),
        name=DATASET_NAME,
        version=version,
        license=LICENSE,
        tasks=TASKS,
    )
    catalog_path = artifacts / "catalog.json"
    if catalog_path.is_file():
        catalog = load_catalog(str(catalog_path))
    else:
        catalog = build_catalog([])
    catalog = upsert(catalog, entry)
    written = Path(write_catalog(str(catalog_path), catalog))
    card = Path(write_card(str(artifacts / "cards"), entry))
    return written, card


def run_guard(raw_csv: Path, artifacts: Path) -> dict[str, Any]:
    """跑一条注定失败的管线（age=999），验证失败节点会被记录。"""
    try:
        with lineage.run("demo_guard") as current:
            rows = ingest(str(raw_csv))
            rows[0]["age"] = "999"
            validate(enrich(clean(rows)))
    except ValueError as exc:
        target = current.save(str(artifacts / "lineage" / "demo_failed.json"))
        summary = current.summary()
        print(f"[guard] caught as expected: {exc}")
        print(
            "[guard] run={0} status={1} failed_nodes={2} ({3}) -> {4}".format(
                current.name,
                current.status,
                summary["failed"],
                type(exc).__name__,
                target,
            )
        )
        return summary
    raise RuntimeError("guard pipeline unexpectedly succeeded")


def main(argv: list[str] | None = None) -> int:
    """示例入口：跑管线、写报告与 catalog、再跑一次失败的 guard。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover
            pass

    parser = argparse.ArgumentParser(description="Run the demo dataset pipeline.")
    parser.add_argument("--variant", choices=["a", "b"], default="a", help="pipeline variant")
    parser.add_argument("--raw", default=str(DEFAULT_RAW), help="raw csv path")
    parser.add_argument("--artifacts", default=str(DEFAULT_ARTIFACTS), help="artifacts directory")
    parser.add_argument("--skip-guard", action="store_true", help="skip the failing pipeline")
    args = parser.parse_args(argv)

    raw_csv = Path(args.raw)
    artifacts = Path(args.artifacts)
    if not raw_csv.is_file():
        print(f"error: raw csv not found: {raw_csv}", file=sys.stderr)
        print("hint : run python examples/make_fixtures.py first", file=sys.stderr)
        return 1

    if args.variant == "b":
        run_name, version, stem = "demo_v2", "1.1.0", "demo_v2"
        fill_strategy, normalise_city = "zero", False
    else:
        run_name, version, stem = "demo_v1", "1.0.0", "demo"
        fill_strategy, normalise_city = FILL_STRATEGY, NORMALISE_CITY

    artifacts.mkdir(parents=True, exist_ok=True)
    current = run_pipeline(
        run_name,
        version,
        raw_csv,
        artifacts,
        fill_strategy=fill_strategy,
        drop_duplicates=DROP_DUPLICATES,
        normalise_city=normalise_city,
    )
    summary = current.summary()
    lineage_path = current.save(str(artifacts / "lineage" / f"{stem}.json"))
    report_path = write_report(artifacts / "lineage" / f"{stem}.md", current, version)
    catalog_path, card_path = update_catalog(artifacts, current, version)

    published = sorted((artifacts / "publish").glob(f"{DATASET_NAME}-{version}.csv"))
    print(f"[main ] run={current.name} status={current.status} nodes={summary['nodes']}")
    if published:
        print(f"[main ] published -> {published[-1]}")
    print(f"[main ] lineage  -> {lineage_path}")
    print(f"[main ] report   -> {report_path}")
    print(f"[main ] catalog  -> {catalog_path}")
    print(f"[main ] card     -> {card_path}")

    if not args.skip_guard:
        run_guard(raw_csv, artifacts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
