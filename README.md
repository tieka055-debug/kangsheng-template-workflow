# 康生模版工作流

把供应商原始 2D 图纸（PDF）批量转换为「康生电子」品牌样式的工程图纸，
回传到飞书 PIM 多维表格。布局位置可以调整，但产品图纸内容一个不能少、一笔不能改。

## 冻结资产（不可再设计）

| 资产 | 说明 |
|---|---|
| `asset_user_bg_plate.png` | 全页背景底图（用户定稿的冰蓝光带图），原样铺底 |
| `asset_single_sample_titleblock.png` | 冻结标题栏（BC-60 认可稿内嵌图 1:1 提取，双列公差+MODEL 大格） |
| `asset_approved_brand_strip_with_dot.png` | K Logo 品牌条 |
| `asset_master_bc60_approved.pdf` | 用户认可的 BC-60 母版 PDF（出处凭证） |

**规则**：标题栏框架、Logo、公司名、每条线、每个格子、所有标签位置全部冻结；
每张图唯一允许的变化 = MODEL 值文字（按源图纸自身图号替换，字号自适应、同色 #0440A8、同光学中心）。

## 单张构建

```bash
python3 work/zcode_build_series.py \
  --src <源.pdf> --out-name <输出名.pdf> \
  --model "<图号>" [--set-rot-270] \
  [--groups-json <布局.json>]   # 缺省 = BC-21 家族布局
```

- 换色映射：黑线→品牌蓝 #0642A8，青色焊盘→金 #E6A21A，灰→浅蓝 #6F9BCF
- 产品内容全部矢量（SVG text-as-path → 裁剪 → show_pdf_page），不栅格化
- 源图框 / Autodesk 水印 / 质源标题栏：裁掉，由康生模板替代

## 批量

```bash
python3 work/batch_runner.py --limit 10 --upload   # 按表格顺序跑 10 张并回传
```

每张五道关：下载 → 方向识别（文字竖排=内容横放 → 转 270°）→ 自动测量内容分组
（墨迹连通域+膨胀聚类，旧图框/水印条带剔除）→ 槽位排版（等比缩放，11 个固定槽位）
→ 构建后遗漏扫描（源图与成品连通域对比，除图框/水印外零遗漏才算 PASS）→
同名覆盖回传飞书「产品表」2D图纸列。

失败/可疑的记入 `batch_state.json`（status=coverage-fail / error），人工处理。

## 飞书

- Base `TxgTbNZV8aieOJsT21pcr9jXnPf`，表 `tblkasFvHs3hl91c`，附件列 `fldesr8bw9`（2D图纸）
- 2D 图纸按系列挂附件，多型号共用一张系列图；同名覆盖 = 上传新文件后
  批量更新记录的附件 token 列表
- 全部 lark-cli 命令走 `--as user`；文件名含括号等特殊字符 → 子进程一律用参数列表调用

## 已完成

BC-21系列塑高2.25H / 1.7H、2D_BC-26系列 2-6P（已覆盖回飞书）。
