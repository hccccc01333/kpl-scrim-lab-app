# 本机 OCR 引擎：RapidOCR + Mimo（Xiaomi-OCR-0）

工作台有两层 OCR，默认都只读本地文件，不调用云端。

| 层 | 引擎 | 用途 | 速度（本机 CPU） |
| --- | --- | --- | --- |
| 快速布局 | `rapidocr-onnxruntime` | 页型、坐标、KDA/经济/伤害/承伤/占比、HUD 逐帧数值 | 秒级/页；录屏 1 fps 约 1–2 分钟 |
| 文字精读 | `mimo-ocr-0`（`SeerRay-Lab/Xiaomi-OCR-0`） | 英雄名、昵称、加载页阵容、团队面板 KDA/金币 | 15–60 秒/短裁剪；整页 2–4 分钟/页 |

## 为什么不是“整页全交给 Mimo”

已用完整 27:6 样本（7 页签）和对应录屏实测：

- **英雄名竖列**：左右各 5/5 正确；合并后 10/10。
- **团队面板单块**：5 行 KDA + 累计金币全对（例：`3/2/6 5061`、`5/1/1 6289`）。
- **数据页整页、左 5 行**：225 秒；数值大多读出，但会把**英雄名与昵称对调**，把等级 7 当成评分，导致评分/伤害列错位。
- **战绩页整页、左 5 行**：141 秒；KDA/经济值正确，但英雄/昵称仍对调，并多输出两列。
- **单行裁剪**：能抄出数值，但参团率/输出占比/承伤占比会错位。

结论：Mimo 的文字识别能力很好，但**列语义**需要坐标锚定。因此默认不把整页结构化抽取交给 Mimo；Mimo 只做定向裁剪，数值列仍由带列头锚点的快速 OCR 读取。

## 模型位置

按以下顺序查找，均不联网：

1. 环境变量 `MIMO_OCR_MODEL` 指向的目录（需含 `config.json` 与 `model.safetensors`）。
2. 项目内 `models/Xiaomi-OCR-0/`。
3. Hugging Face 缓存：
   - `HUGGINGFACE_HUB_CACHE` / `HF_HUB_CACHE` / `HF_HOME`
   - 默认 `~/.cache/huggingface/hub/models--SeerRay-Lab--Xiaomi-OCR-0/snapshots/*/`

本机当前路径可直接查看：

```powershell
python scripts/check_ocr_engine.py
python scripts/check_ocr_engine.py --load
```

## 依赖

```powershell
python -m pip install -r requirements.txt
```

快速 OCR 固定使用 `rapidocr-onnxruntime>=1.4.4,<1.5`。1.4.x 只发布到 Python 3.12，
因此本项目支持 **3.11 / 3.12**，不支持 3.13。

1.4 起 `read_line` 返回 `(text, score)` 二元组（旧版是 `(box, text, score)`），
1.3.0 之前按三元组取值会抛 `IndexError` 并被静默吞掉，导致「整页漏字 → 裁剪补读」
的兜底整条失效。已改为按元素个数自适应，两种返回结构都兼容。

实测同一批样本：战绩页击杀从旧版 1/10 恢复到 **10/10**，结算页击杀与经济 10/10。

Mimo 额外需要 `torch` / `torchvision` / `transformers`；模型权重约 1.7 GB，CPU 推理需要约 3–4 GB 内存。没有安装时，快速 OCR 仍可正常使用，页面会提示“Mimo 未找到”。

## 在页面里使用

- **截图采集**：每个图片行有“Mimo 精读”按钮；每个比赛组有“精读整组”。也可勾选“上传后自动 Mimo 精读”，任务在后台排队，先显示快速结果，完成后自动刷新。
- **录屏采集**：默认“Mimo 精读 + 快速布局”。Mimo 只读加载页阵容和团队面板关键帧；逐帧时钟/金币/击杀仍走快速 OCR。
- **手动英雄修正永远优先**：Mimo 不会覆盖 `heroSource=manual` 的英雄；精读任务保存前会重新读取当前手工值。

## 命令行

截图：

```powershell
# 快速（默认）
python scripts/postgame_screenshot.py "战绩.png" "数据.png" --out report.json

# Mimo 文字列精读（每页 4 次短调用）
python scripts/postgame_screenshot.py "战绩.png" "数据.png" `
  --ocr-engine mimo --mimo-mode columns --out report.json

# 整页实验模式（不推荐日常使用）
python scripts/postgame_screenshot.py "数据.png" --ocr-engine mimo --mimo-mode page
```

录屏：

```powershell
python scripts/replay_video_ocr.py "录屏.mp4" --fps 1 `
  --ocr-engine auto --evidence data/replays/video_ocr/evidence/demo
```

`auto` 在模型可用时执行 Mimo 关键帧精读；`rapid` 只跑快速链路。

## 缓存

Mimo 结果按“模型指纹 + 提示词 + 图片像素”缓存到 `data/ocr_cache/mimo/`。重复打开同一张截图、同一段录屏不会重复跑几分钟的推理。清理：

```powershell
Remove-Item data/ocr_cache/mimo/*.json
```

`MIMO_OCR_CACHE` 可改缓存根目录；`MIMO_OCR_THREADS` 可限制 CPU 线程（默认最多 8）。

## 录制磁盘空间

录屏原文件、报告和证据帧存放在 `data/recordings/<id>/`，不进入 SQLite 或 JSON 备份。默认上限 2 GB；空间不足时上传会直接拒绝并提示，而不是写到一半失败。

```powershell
# 把录屏库放到空间更充足的盘
$env:KPL_RECORDINGS = "E:\kpl-recordings"
python server.py
```

## 实测边界

- 纯 CPU：Mimo 整页 2–4 分钟/页；7 页纯整页精读约 15–25 分钟，仍可能错列。
- 低清/裁切录屏：960×432 的 20:9 录制，团队面板 KDA 用 Mimo 单块可读；逐帧顶部金币/击杀会因小字和压缩产生回退，报告会标记，不能当精确终局。
- 英雄身份：加载页的皮肤标题常被连读；录屏缺同局截图/`.abc` 时，英雄仍应人工确认。
- 所有识别结果都是候选，不自动进入正式统计。
