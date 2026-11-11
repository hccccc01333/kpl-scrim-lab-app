# 部署指南（本机 / 局域网 / Docker）

目标是让另一个人 clone 仓库后，不依赖原作者的设备、游戏进程或私有快照，
也能启动核心工作台并导入自己的数据。

## 1. 运行要求

- Python **3.10+**
- **OCR 是必需能力**：`requirements.txt` 会安装 RapidOCR、torch、torchvision、
  transformers（Mimo 精读）
- Mimo **模型权重**不随 pip 包分发；按 [OCR 引擎说明](ocr_engine.md)
  设置 `MIMO_OCR_MODEL` 或放入项目缓存/模型目录
- 视频抽帧需要系统 `ffmpeg`
- 不需要 MuMu、ADB、游戏账号或 `.abc` 回放才能启动工作台。

## 2. 本机启动

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python server.py
```

打开 <http://127.0.0.1:8766/>（V3 界面）。

### Linux / macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

首次启动会自动创建 `data/training.sqlite3` 和所需目录。停止用 `Ctrl+C`。

### Mimo 权重

`requirements.txt` 已安装 Mimo 的 Python 依赖，但模型权重需要单独准备：

```bash
export MIMO_OCR_MODEL=/srv/models/Xiaomi-OCR-0
# 或把模型放到项目 models/Xiaomi-OCR-0/
```

详见 [OCR 引擎说明](ocr_engine.md)。没有权重时 RapidOCR/快速 OCR 仍可用，
但 Mimo 精读不可用；部署自检会明确报告这一点。

## 3. 配置

所有配置都用环境变量，默认值适合本机：

| 变量 | 默认 | 说明 |
|---|---|---|
| `TRAINING_HOST` | `127.0.0.1` | HTTP 绑定地址；Docker/局域网用 `0.0.0.0` |
| `TRAINING_PORT` | `8766` | HTTP 端口 |
| `TRAINING_DB` | `data/training.sqlite3` | 主数据库 |
| `ANALYSIS_MATCHES` | `data/matches` | 分析比赛 JSON |
| `ANALYSIS_IMPORTS` | `data/imports` | 导入数据 |
| `ANALYSIS_OFFICIAL` | `data/official_replays` | 营地回放 |
| `ANALYSIS_BUILDS` | `data/builds` | 出装时间轴 |
| `KPL_RECORDINGS` | `data/recordings` | 录屏原文件 |
| `TRAINING_ALLOWED_HOSTS` | `127.0.0.1,localhost,::1` | 允许的 Host |
| `TRAINING_ALLOW_REMOTE` | 关闭 | 允许非本机 Host；仅可信局域网使用 |

默认只接受 loopback Host，并带同源写请求检查。**没有内置登录/权限系统**；
不要把端口直接暴露到公网。

示例：

```bash
export TRAINING_DB=/srv/kpl/data/training.sqlite3
export KPL_RECORDINGS=/srv/kpl/recordings
export TRAINING_HOST=0.0.0.0
export TRAINING_ALLOW_REMOTE=1   # 仅在可信局域网
python server.py
```

## 4. Docker

核心镜像包含 RapidOCR/Mimo 的 Python 依赖和 ffmpeg，但不包含 Mimo 模型权重；
权重通过卷或 `MIMO_OCR_MODEL` 挂载：

```bash
docker compose up --build
```

打开 <http://127.0.0.1:8766/>（V3 界面）。数据持久化在 `./data`。
默认 compose 只映射到 `127.0.0.1`；需要局域网访问时修改端口映射并设置
`TRAINING_ALLOW_REMOTE=1`。

也可以直接：

```bash
docker build -t kpl-workbench .
docker run --rm -p 127.0.0.1:8766:8766 \
  -v "$PWD/data:/app/data" \
  -e TRAINING_HOST=0.0.0.0 \
  -e TRAINING_DB=/app/data/training.sqlite3 \
  kpl-workbench
```

## 5. 安装后自检

```bash
python scripts/check_deploy.py
python -m unittest tests.test_replay_checkpoints_api -v
```

`check_deploy.py` 会用临时数据库启动应用，检查健康接口、回放列表、状态页和
静态资源，不写真实数据。

## 6. 数据与备份

- 业务数据：`data/training.sqlite3`
- 分析/导入/营地/时间轴：各自的 `data/...` 目录
- 录屏原文件：`KPL_RECORDINGS` 目录，默认 `data/recordings`
- 备份：停服后复制整个 `data/`；或使用页面内的 JSON 备份（原图/识别记录）

不要提交、分享或上传：

- `data/` 下的原始进程快照、arena/context dump、账号/token 类内存；
- 游戏 `.abc`/`.ope` 原文件；
- `host/fixtures`、`host/build` 中的设备/本机二进制；
- `.workbuddy/` 研究记录。

## 7. 常见问题

- **`ModuleNotFoundError: fastapi`**：没有激活 venv，或装到了别的 Python。
- **端口占用**：设置 `TRAINING_PORT=8767`。
- **页面 403「仅允许本机访问」**：Host 不是 loopback；本机用
  `http://127.0.0.1:8766`，局域网/Docker 显式设置 `TRAINING_ALLOW_REMOTE=1`。
- **截图 OCR 不可用**：安装 `requirements.txt`（RapidOCR）；Mimo 另装
  `requirements-ocr.txt`。
- **视频 OCR 报 ffmpeg**：安装系统 ffmpeg 并确认 `ffmpeg -version`。
- **想清空重来**：停服后删除 `data/training.sqlite3`（会丢失业务数据）。

## 8. 开源边界

仓库不应包含游戏客户端二进制、`.abc` 回放、原始进程内存、账号信息或
未授权的第三方数据。`docs/` 里的逆向研究记录是可选背景材料；部署核心
工作台不依赖它们。许可证由项目所有者最终确定。
