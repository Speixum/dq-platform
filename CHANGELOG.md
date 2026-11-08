# Changelog

## 0.1.0

首个版本，把六个独立工具仓库串成一条可复现流水线。

**编排层**
- `dqplat.config`：TOML 流水线定义（步骤 / 工作目录 / 依赖 / 产物 / 超时 / 可选性）
- `dqplat.runner`：顺序执行、逐步日志、耗时统计、产物 sha256、`manifest.json`（`dq-run/1.0`）
- `dqplat.contracts`：`pii-hits/1.0`、`dataset-lineage/1.0`、`data-quality-report/1.0` 结构校验
- `dqplat.cli`：`run` / `list` / `show` / `validate`，退出码 0/1/2
- 占位符 `{root}` `{out}` `{python}`；缺依赖跳过（可选步骤）或失败（必需步骤）

**流水线**
- `demo`：fixtures → pii → lineage → report，开箱即跑，约 0.5 秒
- `full`：prep → qc → cost → fixtures → pii → lineage → report，缺数据自动跳过

**其他**
- 27 个单元测试（配置解析 / 契约校验 / 执行器 / CLI）
- 六个源仓库以精简镜像方式放在 `vendor/`，不改其代码；只保留运行所需子集（全仓库 97 个文件），出处、裁剪范围与同步策略见 NOTICE.md
