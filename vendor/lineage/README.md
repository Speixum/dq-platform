# data-lineage-lite

零依赖的数据集生产链路线血追踪库：给普通 Python 脚本加装饰器，就能得到每次运行的步骤图、参数快照、输入输出内容哈希、数据规模指标，以及可对比的 JSON、可渲染的 mermaid/dot/ASCII 树和数据集卡片。

## 安装与一条命令跑通

需要 Python 3.9+，**没有任何第三方依赖**，安装不需要联网：

```bash
python -m pip install -e .
```

一条命令跑通示例（在仓库根目录执行，Windows 上用两行）：

```bash
python examples/make_fixtures.py
python examples/pipeline_demo.py
```

示例会生成 200 行带缺失/重复/混合类型的 CSV，跑一条 5 步管线，并在 `artifacts/` 下写出 lineage JSON、markdown 报告、入库 CSV+manifest、catalog 与数据集卡片；最后还会跑一条故意失败的管线，证明失败节点同样被记录。

## 能力清单

- **追踪**：`@lineage.track("step")` 装饰器 + `with lineage.run("name"):` 上下文，基于 `contextvars`，支持嵌套 run 与多线程隔离；节点 id 为 `{run}/{step}#{seq}`。
- **哈希**：文件按 1MB 分块 sha256；表格对象（`list[dict]`、二维 `list`、`dict[str, list]`、鸭子类型 DataFrame）按规范化内容哈希，**列顺序无关、行顺序有关**；不可哈希对象退化为 `unstable:<type>#<short>`。
- **画像**：纯标准库计算 rows/cols/columns/null_ratio/dup_rows/类型推断，作为节点的 `fingerprint`。
- **渲染**：ASCII 文本树、mermaid（失败节点红色 `classDef`）、Graphviz dot。
- **对比**：节点级 diff（状态/参数/输出哈希）+ 质量漂移（rows、null_ratio、dup_rows）。
- **catalog**：把多个 run 聚合成 `catalog.json`，并生成中文数据集卡片 markdown（名称/版本/规模/字段/许可/适用任务/更新时间）。
- **CLI**：`render`、`diff`、`show`、`list`、`catalog`、`card` 六个子命令，控制台骨架统一 ASCII（`+ - |`），打印前统一 UTF-8 重配置。

## 示例产物长什么样

```text
[main ] run=demo_v1 status=ok nodes=5
[main ] published -> ...\artifacts\publish\demo_users-1.0.0.csv
[main ] lineage  -> ...\artifacts\lineage\demo.json
[main ] report   -> ...\artifacts\lineage\demo.md
[main ] catalog  -> ...\artifacts\catalog.json
[main ] card     -> ...\artifacts\cards\demo_users.md
[guard] caught as expected: validation failed: 1 problems, first=row 1: age out of range: 999.0
[guard] run=demo_guard status=failed failed_nodes=1 (ValueError) -> ...\artifacts\lineage\demo_failed.json
```

渲染那次失败的 run（mermaid 里失败节点会被染红）：

```bash
python -m lineage render artifacts/lineage/demo_failed.json --format mermaid
```

```text
flowchart TD
  n00["ingest <br/> ok <br/> 6.3ms"]
  n01["clean <br/> ok <br/> 6.2ms"]
  n02["enrich <br/> ok <br/> 6.0ms"]
  n03["validate <br/> FAILED <br/> 3.5ms"]
  n00 -->|table| n01
  n01 -->|table| n02
  n02 -->|table| n03
  classDef failed fill:#fdd
  class n03 failed
```

默认格式是 ASCII 树，适合直接贴进终端或 markdown：

```text
demo_v1 [ok] nodes=5 edges=4
+-- 01 ingest [ok] (4.5 ms)
    |-- <return> table sha256:81c2228e... rows=200 cols=7 null_ratio=0.0179
    +-- 02 clean [ok] (5.6 ms)
        |-- <return> table sha256:fd374803... rows=192 cols=7 null_ratio=0.0074
        +-- 03 enrich [ok] (6.0 ms)
            ...
            +-- 05 publish [ok] (12.1 ms)
```

## 亲手验证 diff 会报出变化

diff 以 `step#序号` 作为节点键，所以两次运行 run_id 不同也能对齐；先准备基线：

```bash
python examples/make_fixtures.py
python examples/pipeline_demo.py
```

**方式一：改参数（同样的数据，不同的填充策略）**

`--variant b` 内置了另一套参数（`FILL_STRATEGY = "zero"`），不用改源码，跑两次就能对比：

```bash
python examples/make_fixtures.py
python examples/pipeline_demo.py                # demo.json
python examples/pipeline_demo.py --variant b    # demo_v2.json
python -m lineage diff artifacts/lineage/demo.json artifacts/lineage/demo_v2.json
```

```text
before: demo_v1 (ok)
after : demo_v2 (ok)
summary: added=0 removed=0 changed=3 unchanged=2 drift=0

changed nodes:
+---------+----------+--------+---------+-------+
| step    | status   | params | outputs | drift |
+---------+----------+--------+---------+-------+
| clean   | ok -> ok | yes    | 1       | -     |
| enrich  | ok -> ok | yes    | 1       | -     |
| publish | ok -> ok | yes    | 1       | -     |
+---------+----------+--------+---------+-------+
```

参数差异落在 `clean`、`enrich`、`publish` 三步，数据规模没变，所以 `drift=0`。

**方式二：改数据规模（质量漂移）**

先跑 240 行留底，再跑默认 200 行对比：

```bash
python examples/make_fixtures.py --rows 240
python examples/pipeline_demo.py --skip-guard
cp artifacts/lineage/demo.json artifacts/lineage/demo_240.json
python examples/make_fixtures.py
python examples/pipeline_demo.py --skip-guard
python -m lineage diff artifacts/lineage/demo_240.json artifacts/lineage/demo.json
```

```text
before: demo_v1 (ok)
after : demo_v1 (ok)
summary: added=0 removed=0 changed=5 unchanged=0 drift=4

changed nodes:
+----------+----------+--------+---------+-----------------------------------+
| step     | status   | params | outputs | drift                             |
+----------+----------+--------+---------+-----------------------------------+
| clean    | ok -> ok | yes    | 1       | rows 232->192 null 0.0068->0.0074 |
| enrich   | ok -> ok | yes    | 1       | rows 232->192 null 0.0047->0.0052 |
| ingest   | ok -> ok | no     | 1       | rows 240->200 null 0.0173->0.0179 |
| publish  | ok -> ok | yes    | 1       | rows 232->192 null 0.0047->0.0052 |
| validate | ok -> ok | yes    | 1       | -                                 |
+----------+----------+--------+---------+-----------------------------------+
```

`validate` 的 `params` 之所以也是 `yes`，是因为演示里它把接收到的二维表（含行数）原样记进了参数——数据一变，这个参数就变，属于预期行为。

`artifacts/` 与 `examples/data/` 都是脚本生成的，已在 `.gitignore` 里；新克隆后先跑一遍 `make_fixtures.py` 和 `pipeline_demo.py` 即可复现，不需要把产物提交进仓库。

## 在自己的代码里用

```python
import lineage

@lineage.track("load")
def load(path: str) -> list[dict]:
    ...

@lineage.track("build")
def build(rows: list[dict]) -> list[dict]:
    ...

with lineage.run("nightly") as run:
    rows = load("data/raw.csv")
    out = build(rows)

run.save("artifacts/lineage/nightly.json")
print(run.summary())  # {"run_id": ..., "status": "ok", "nodes": 2, "failed": 0, ...}
```

- 不在 `run` 里调用被装饰函数时，装饰器直接透传，零开销、零副作用。
- 步骤抛异常时先记录失败节点（`status="failed"` + `error={type,message,traceback}`）再原样抛出，不吞异常。
- `params` 逐参数做 JSON 快照；不可序列化的对象降级为 `repr` 并把节点标为 `unstable=true`。

## catalog 与数据集卡片

```bash
python -m lineage catalog artifacts/lineage --out artifacts/catalog.json --cards-dir artifacts/cards --license CC-BY-4.0 --tasks analytics,profiling
python -m lineage card artifacts/lineage/demo.json --name demo_users --license CC-BY-4.0
```

`catalog.json` 顶层 `schema` 为 `dataset-catalog/1.0`，每条记录含名称/版本/规模/列/缺失率/重复行/内容哈希/许可/任务/来源 run/卡片路径；卡片写到 `cards/<name>.md`。

## 数据契约

lineage JSON 顶层（与跨工具约定一致）：

```json
{
  "schema": "dataset-lineage/1.0",
  "run_id": "demo_v1-20261107T174954Z",
  "name": "demo_v1",
  "started_at": "2026-11-07T17:49:54Z",
  "finished_at": "2026-11-07T17:49:54Z",
  "status": "ok",
  "env": {"python": "3.11.9", "platform": "win32", "cwd": "."},
  "nodes": [...],
  "edges": [{"from": "demo_v1/ingest#01", "to": "demo_v1/clean#02", "label": "table"}]
}
```

节点：

```json
{
  "id": "demo_v1/ingest#01",
  "step": "ingest",
  "seq": 1,
  "status": "ok",
  "started_at": "2026-11-07T17:49:54Z",
  "duration_ms": 4.461,
  "params": {"path": "examples/data/raw_users.csv"},
  "inputs": [{"ref": "path", "kind": "file", "hash": "sha256:8c43...", "bytes": 10532}],
  "outputs": [{
    "ref": "<return>",
    "kind": "table",
    "hash": "sha256:81c2...",
    "bytes": null,
    "fingerprint": {"rows": 200, "cols": 7, "columns": ["user_id", "..."], "null_ratio": 0.0179, "dup_rows": 8, "types": {"user_id": "str", "...": "mixed"}}
  }],
  "error": null,
  "unstable": false
}
```

其它约定：所有 JSON 为 UTF-8、`ensure_ascii=False`、缩进 2；时间统一 ISO8601 UTC 秒精度（`2026-11-08T01:35:00Z`）；哈希统一 `sha256:` 前缀；文件按 1MB 分块。

## 设计取舍

- **contextvars 而不是全局栈**：同一进程里多线程各自跑管线互不串台，也不需要 `threading.local` 加锁；嵌套 run 通过复制当前节点作用域实现，子 run 的节点带父前缀，父 run 结束时能枚举整棵子树。
- **列顺序无关、行顺序有关**：列名先排序再吸收，改列顺序不算内容变化；行顺序保留，因为下游经常按顺序赋值（如写入 CSV 的行序），静默容忍会掩盖真实变更。
- **params 逐参数快照**：整体快照会把 200 行表格塞进 JSON（曾把 demo.json 撑到 8000 行）；逐参数后，表格只留 `{"<table>": [...列名], "<rows>": 200}` 摘要。
- **失败也记录**：错误是血缘的一部分，失败节点保留 inputs/params/error/traceback，便于事后定位"哪一步、什么输入、什么异常"。
- **pandas 只探测不导入**：用 `hasattr(obj, "columns") and hasattr(obj, "to_dict")` 判定表对象，装了 pandas 能用，没装也不影响，符合零依赖约束。
- **diff 用 step#序号对齐**：run_id 每次不同，按 id 比会全量误报；step 与出现序号稳定，才比得出真实变化。
- **catalog 用 JSON 文件**：单机小团队不需要数据库，JSON 便于 code review 与 git diff；写入是"读-改-写"，只在单进程内安全。

## 已知限制 / 未实现

- 表格哈希需要把行读进内存，没有流式表指纹；分块只作用于文件哈希。
- `catalog.json` 的并发写没有文件锁，多进程同时写会互相覆盖。
- diff 只做到节点级与输出画像级，不做行级/单元格级差异。
- 没有 Web UI、数据库后端、远端对象存储上传。
- `params` 只保证 JSON 可序列化内容稳定；自定义对象一律降级 `repr` 并标 `unstable`，此时哈希不可用于跨机器比对。
- 符号链接按普通文件读取；超大文件哈希耗时随体积线性增长。
- 时间戳为秒精度，同一秒内的多次运行只靠 run_id 区分。

## 与 SPEC 的偏差（及原因）

1. **嵌套 run 的节点 id**：SPEC 只规定 `{run}/{step}#{seq}`。实现中嵌套时子 run 作用域名取 `父/子`，于是节点 id 为 `outer/inner/work#01`。原因：保持单层与嵌套同一套解析规则，且父 run 仍可通过前缀枚举整棵子树。
2. **新增两个内部模块**：`lineage/errors.py`（错误类型）与 `lineage/io.py`（JSON 读写与 schema 校验）。SPEC 未列，但避免 tracker/catalog/cli 三处重复实现。
3. **表格输出没有字节数**：`outputs[].bytes` 对 `kind="table"` 为 `null`（表格是内存对象，没有文件长度）。SPEC 只要求字段存在，这里选择 `null` 而不是编造 0。
4. **catalog / diff 的顶层 schema** 分别定为 `dataset-catalog/1.0` 与 `lineage-diff/1.0`，SPEC 只要求"顶层含 schema"，命名按同一 `<域>/<版本>` 风格自洽。
5. **CLI 额外选项**：在 SPEC 要求的六个子命令上补了 `--json`、`-o/--out`、`--license` 等开关，命令集与语义未变。
6. **示例私有格式**：`examples/` 的 `publish-manifest/1.0` 只是 demo 的入库清单，不属于库的对外契约。

## 目录结构

```text
data-lineage-lite/
+-- lineage/
|   +-- __init__.py      公共出口
|   +-- __main__.py      python -m lineage
|   +-- cli.py           render|diff|show|list|catalog|card
|   +-- tracker.py       track 装饰器 / run 上下文 / 节点与边
|   +-- hashing.py       文件与表格内容哈希、fingerprint
|   +-- profile.py       存量指标与类型推断
|   +-- catalog.py       catalog.json 与数据集卡片
|   +-- render.py        mermaid / dot / ASCII 树
|   +-- diff.py          节点级比较与质量漂移
|   +-- io.py            JSON 读写与 schema 校验
|   +-- errors.py        错误类型
|   +-- py.typed         类型标记
+-- tests/               67 个 unittest 用例
+-- examples/
|   +-- make_fixtures.py 生成 200 行示例 CSV
|   +-- pipeline_demo.py 5 步演示管线
+-- pyproject.toml       dependencies = []
+-- README.md
+-- LICENSE (MIT)
+-- .gitignore
```

## 开发与测试

```bash
python -m unittest discover -s tests -v
```

测试只用标准库 `unittest`，覆盖哈希稳定性与敏感性、装饰器成功/失败/嵌套、run 封口、profile 指标、catalog 聚合、diff 漂移、mermaid 结构与 CLI 退出码。

## License

MIT，见 [LICENSE](LICENSE)。
