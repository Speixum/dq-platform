# vendor/qc (placeholder)

本目录对应独立仓库 [Speixum/dataset-qc-toolkit](https://github.com/Speixum/dataset-qc-toolkit)，
用于入库前的重复图检测、标注统计与划分泄漏检查。

当前未随本仓库分发。补全步骤：

1. 把该仓库取下来，内容直接放在本目录（保持入口文件在 `vendor/qc/` 下）
2. 创建一个空标记文件，告诉编排层"这个模块已经真实落盘"：

   ```
   type nul > vendor\qc\.vendored        # cmd
   New-Item vendor\qc\.vendored -ItemType File   # PowerShell
   ```

3. 按真实入口修改 `pipelines/full.toml` 里 `qc` 步骤的 `command`

没有 `.vendored` 时，`qc` 步骤会被判定为"依赖缺失"并跳过，其余五步照常运行。
