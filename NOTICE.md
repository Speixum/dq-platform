# NOTICE

本仓库的 `vendor/` 目录是以下六个独立仓库的镜像副本，用于让整条流水线自包含、clone 即跑。
代码版权归各源仓库所有，各自保留原有 LICENSE；本仓库新增的编排层（`dqplat/`、`pipelines/`、`tests/`）为 MIT。

| 目录 | 源仓库 | 用途 |
|---|---|---|
| `vendor/prep` | [Speixum/dataset-prep-toolkit](https://github.com/Speixum/dataset-prep-toolkit) | Labelme 多边形 → 二值掩码、类别统计、掩码核对 |
| `vendor/qc` | [Speixum/dataset-qc-toolkit](https://github.com/Speixum/dataset-qc-toolkit) | 重复图检测、标注统计、划分泄漏检查（**当前未分发**，见该目录 README） |
| `vendor/cost` | [Speixum/dirty-data-cost](https://github.com/Speixum/dirty-data-cost) | 数据缺陷的精度代价量化、免训练质量指标 |
| `vendor/pii` | [Speixum/pii-scan](https://github.com/Speixum/pii-scan) | 身份证 / 手机号 / 银行卡 / 邮箱等敏感信息扫描与脱敏 |
| `vendor/lineage` | [Speixum/data-lineage-lite](https://github.com/Speixum/data-lineage-lite) | `@track` 血缘采集、Mermaid 渲染、两次运行 diff |
| `vendor/qdash` | [Speixum/quality-dashboard](https://github.com/Speixum/quality-dashboard) | 多工具 JSON 汇总为单文件离线 HTML 报告 |

## 本仓库只带运行所需的子集

为了让整个仓库控制在一百个文件以内（便于没有 git 的环境一次性上传或拷贝），`vendor/` 下的镜像做过裁剪：

| 保留 | 裁掉 |
|---|---|
| 各工具的包代码与入口、许可证、README | 各源仓库的 `tests/` |
| `vendor/pii/data/sample.txt`（demo 用的虚构样本） | `vendor/pii/examples/` |
| `vendor/lineage/examples/`（demo 用固定夹具生成器与示例流水线） | `vendor/qdash/examples/` |
| `vendor/cost/src` 的核心实验脚本、`docs/`、`results/versions/` 三个汇总文件、`data/splits/split_seed42.json` | `vendor/cost/versions` 的逐版本 `labels.csv`、`results/` 的逐次运行明细、图表生成脚本 |

需要完整镜像时，直接 clone 上表对应的源仓库，把内容覆盖进同名目录即可；裁剪不影响 `python -m dqplat run demo`。

## 同步策略

- **源仓库为准**。修 bug、改功能都在源仓库进行，改完再同步到 `vendor/`。
- 同步时不要覆盖 `vendor/qc/README.md` 这类本地说明文件。
- 复制时排除 `.git/`、`__pycache__/`、`artifacts/`、`reports/` 等生成物。

## 为什么不直接用依赖或 submodule

- 目标环境常常没有网络、也不方便装包，六个工具都是零第三方依赖的纯标准库项目；
- submodule 需要 git 操作，而本仓库的使用场景包含"网页上传/离线拷贝"；
- 镜像副本让"下载解压 → 一条命令跑通"成立。
