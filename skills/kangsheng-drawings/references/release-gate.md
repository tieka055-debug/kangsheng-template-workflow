# 本地发布准备门禁

命令：Python 3 执行 `scripts/release_gate.py`，参数为 manifest JSON 的路径。相对文件路径以 manifest 所在目录解析。退出 0 为记录合格，退出 1 为阻断；只读，不联网、不上传。

manifest 顶层字段：
- `schema_version`: 1
- `artifacts`: 非空数组，每项 `id`（唯一字符串）、`role`、`path`、`sha256`。角色 source/output/config/code/evidence 都至少有一个。所有实际输入、模板、运行代码和配置均应登记；不漏报由复核者负责，工具不能自动发现隐含依赖。
- `sources`: 数组，每项 `artifact`（source ID）、`page_count`（正整数）、`reviewed_pages`（恰好覆盖全部页的一基页码）。每个 source 必须有一条。
- `outputs`: 同样结构，artifact 指向 output。每个 output 必须有一条。实际 PDF 页数由独立核查者确认，工具不解析 PDF。
- `groups`: 非空数组，每项 `id` 唯一、`source`、`source_page`、`kind`、`placements`。placements 非空，每项 output/page 指向已登记目标页。每个源页至少一个内容组。kind 为 view/pcb/table/specification/technical_titleblock/other。
- table 组额外字段 `source_rows`、`source_columns`、`verified_rows`、`verified_columns` 均为正整数，前后相等；行数包括表头、列数按原表计。`cells_verified` 必须为 true，代表复核者逐格核对完成，不是软件自动证明。
- `checks`: 恰有以下必需项（可有其他项）：content_inventory, dimensions_symbols, tables, materials_notes, technical_fields, visual_legibility, no_clipping_overlap, page_mapping。每项包含 `status: "pass"`、非空 `reviewer`、带时区 ISO `reviewed_at`、`evidence`（非空 evidence ID 数组）。日期不接受未来日期。

先登记原图清单，再制作输出，最后复核。不可为通过门禁虚构 reviewer、证据、表格行数或把 REVIEW 改成 PASS。证据应是实际原图-成品对照、逐格核对记录、渲染图及缺陷处理记录。

这个工具验证声明结构、文件哈希和映射一致性；不检测人工漏建内容组、不验证图像中的工程数值，也不替代用户样板批准。没有完整原图时，门禁应保持失败。
