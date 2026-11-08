# dq-platform

[![tests](https://github.com/Speixum/dq-platform/actions/workflows/tests.yml/badge.svg)](https://github.com/Speixum/dq-platform/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![deps](https://img.shields.io/badge/dependencies-0-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

把六个独立的数据工具仓库串成**一条可复现的流水线**：编排层只通过子进程调用各仓库自带的 CLI，
不 import 它们的模块、不改它们的代码，每一步的产物都落盘并登记 sha256。

零第三方依赖，纯标准库，Python ≥ 3.11，不联网。

## 快速开始

```
python -m dqplat run demo
```

一条命令依次完成：造演示夹具 → PII 扫描 → 血缘采集 → 生成单文件 HTML 报告，
产物全部落在 `artifacts/runs/<时间戳>/` 下，约 0.5 秒跑完。

在仓库根目录执行即可；也可以装成命令后用 `dqplat run demo`：

```
pip install -e .
dqplat run demo
```

想先看会执行什么而不真跑：

```
python -m dqplat run demo --dry-run
```

## 它解决什么问题

六个仓库各自能跑，但组合使用时有三件事没人管：

1. **产物在哪、是不是这次产生的** —— 每次运行一个独立目录，产物路径、大小、sha256 全部写进 `manifest.json`；
2. **某一步失败之后怎么办** —— 失败即停，日志逐步骤落盘，重跑可用 `--resume` 复用未变化的上游产物；
3. **缺数据时会不会崩** —— 每步声明 `requires`，缺数据时跳过并给出原因，而不是抛异常。

## 命令

| 命令 | 作用 |
|---|---|
| `python -m dqplat run <pipeline>` | 执行一条流水线 |
| `python -m dqplat run <pipeline> --dry-run` | 只打印解析后的命令，不执行 |
| `python -m dqplat run <pipeline> --only a,b` | 只跑指定步骤 |
| `python -m dqplat run <pipeline> --skip c` | 跳过指定步骤 |
| `python -m dqplat run <pipeline> --resume <run目录>` | 复用上次运行中未变化的步骤 |
| `python -m dqplat run <pipeline> --run-dir <目录>` | 指定运行目录 |
| `python -m dqplat run <pipeline> --json` | 运行并输出完整 manifest |
| `python -m dqplat list <pipeline>` | 列出步骤、工作目录、依赖数 |
| `python -m dqplat show <run目录>` | 汇总一次运行 |
| `python -m dqplat validate <文件...>` | 按共享 JSON 契约校验产物 |

退出码：`0` 成功、`1` 步骤失败、`2` 用法/配置错误。

## 两条现成流水线

- `pipelines/demo.toml`：fixtures → pii → lineage → report，**开箱即跑**。
- `pipelines/full.toml`：prep → qc → cost → fixtures → pii → lineage → report，
  前三个步骤依赖外部数据（数据集目录、NEU-CLS 图像、qc 仓库），**缺什么跳什么**。

## 目录结构

```
dq-platform/
  dqplat/            # 编排层（唯一新写的代码）
    config.py        #   TOML -> Step/Pipeline，占位符 {root} {out} {python}
    runner.py        #   顺序执行、日志、耗时、sha256、manifest
    contracts.py     #   pii-hits/1.0、dataset-lineage/1.0、data-quality-report/1.0 的结构校验
    cli.py           #   run / list / show / validate
  pipelines/         # 流水线定义（TOML）
  vendor/            # 六个源仓库的精简镜像（只留运行所需子集），见 NOTICE.md
  tests/             # 27 个单元测试，只用标准库 unittest
  .github/workflows/ # CI：3.11 / 3.12 两个版本跑测试与 demo
```

## 运行清单（manifest.json）

每次运行在 `artifacts/runs/<stamp>/manifest.json` 写一份 `dq-run/1.0`：

```json
{
  "schema": "dq-run/1.0",
  "pipeline": {"name": "demo", "version": "1.0"},
  "status": "ok",
  "steps": [
    {"id": "pii", "status": "ok", "exit_code": 0, "duration_ms": 110.2,
     "command": ["python", "-m", "piiscan", "scan", "..."],
     "log": "artifacts/runs/.../logs/pii.log",
     "produces": [{"path": ".../pii.json", "bytes": 42291, "sha256": "..."}]}
  ]
}
```

`status` 只有四种：`ok` / `failed` / `skipped`（缺依赖或被过滤）/ `dry-run`。

## 设计取舍

- **不 import，只调 CLI**。避免跟六个仓库的内部 API 绑死；它们各自升级，编排层不用跟着改。
- **不引入第三方依赖**。目标场景包含内网、无网环境，`pip install` 本身就是障碍。
- **镜像而非 submodule**。网页上传、离线拷贝都能用；代价是改动要在源仓库做、再同步。
- **不替用户决定"缺数据怎么办"**。缺 `requires` 就跳过并写清原因，跑完整条链的人能看到自己少了哪一步。

## 边界

- 不联网、不写注册表；所有路径都从仓库根推导（`--root` 可覆盖），没有写死的绝对路径；
- `demo` 全程只往运行目录写，跑完 `vendor/` 里不会多出一个文件；
- `prep` / `cost` 处理真实数据集时会在各自目录下生成中间文件（已列入 gitignore）；
- `vendor/` 下的代码是镜像，出问题请回源仓库修，别在这里改；
- `vendor/` 是**精简镜像**：省掉了各源仓库的 `tests/`、示例数据、逐版本结果明细与图表脚本，全量请回各自源仓库取；
- `vendor/qc` 目前是占位目录（原仓库未分发），补齐方式见 `vendor/qc/README.md`；
- 不负责数据采集与标注本身——本仓库只负责"把已有的工具按顺序跑起来并留痕"。

## 许可

本仓库新增代码（`dqplat/`、`pipelines/`、`tests/`）为 MIT；
`vendor/` 下各仓库沿用其原有许可，见 [NOTICE.md](NOTICE.md)。
