# 景区讲解数字人（本地部署）

基于 [OpenTalking](https://github.com/datascale-ai/opentalking) 在本机搭建的景区讲解数字人工作台。
代码与模型跑在 **WSL2 Ubuntu** 里，配置 / 人设 / 知识库 / 脚本放在本目录（Windows 侧），方便编辑和备份。

## 在仓库中的位置与协作方式

本目录是 [`ren-yi-NUDT/Xiao-Juan`](https://github.com/ren-yi-NUDT/Xiao-Juan) 仓库的
`digital-human/` 子目录。仓库根目录的 `main.py` / `lmam/` 是小卷机器人主程序，两者互不干扰。

```
Xiao-Juan/
├── main.py, lmam/, scripts/, ...   ← 小卷机器人（原有内容）
└── digital-human/                  ← 本目录：景区讲解数字人部署
    ├── config/env.scenic.example   ← 配置模板（可入库）
    ├── config/env.scenic           ← 本机真实配置，含 API Key（已 gitignore，不要提交）
    ├── docs/                       ← 操作手册 / 部署手册 / 导入指南
    ├── knowledge/灵山胜境/         ← 27 篇讲解词（已转成 md，可直接重建知识库）
    ├── persona/                    ← 人设包
    ├── scripts/                    ← 部署/导入/重建脚本
    ├── source-data/                ← 两份源 docx（知识库的原始出处）
    └── 素材/                       ← 本地素材，已 gitignore（含 37 MB 录屏）
```

日常改代码/文档后提交：

```powershell
cd "D:\项目\xiao_juan\Xiao-Juan"
git status
git add digital-human
git commit -m "说明改了什么"
git push
```

> 脚本已经改成**从自身位置推导项目路径**，所以整个 `Xiao-Juan` 目录挪到别处也不会失效。
> 提交前务必确认 `git status` 里没有 `env.scenic`、`.mp4`、`.wav` 等本地文件。
> 完整协作流程（分支命名、PR、禁止提交的内容、新机器配置）见 [`docs/Git协作指南.md`](docs/Git协作指南.md)。

## 一、本机环境结论（已实测）

| 项目 | 实测结果 | 影响 |
| --- | --- | --- |
| 系统 | Windows + WSL2 `Ubuntu 22.04.1`（已在运行） | 官方推荐路线，必须在 WSL 内跑，不能放 `/mnt/d` |
| GPU | RTX 5060 Laptop **8 GB**（驱动 580.88，CUDA 13.0） | 够跑 Wav2Lip（≥8 GB）与低分辨率 QuickTalk；跑不了 MuseTalk/FlashTalk |
| 内存 / 磁盘 | 34 GB / WSL 内剩 911 GB | 充足 |
| Python | WSL 内系统版本为 3.10 与 3.11.0rc1（rc 版不可用） | 已改用 uv 托管的 3.11.9 |
| Node | v18.20.8 | 满足 WebUI（≥18） |
| uv | 已装 `~/.local/bin/uv` 0.13.7 | 依赖管理 |
| ffmpeg | 系统未装 | **STT(dashscope) 会失败**，见下方说明 |

> 注意：`requires-python` 已从 `>=3.10` 收窄为 `>=3.11`。
> 原因：`quicktalk-cuda` extra 依赖 `onnxruntime-gpu>=1.24.4`，该包只支持 Python ≥3.11，
> 上游 `>=3.10` 会让 uv 在 3.10 分支解析失败。这是本机唯一改动的上游文件。

> **ffmpeg 说明（2026-11-17 核对）**：正常用 `scripts/start_unified.sh` 启动时，
> `quickstart_resolve_ffmpeg()`（`scripts/quickstart/_helpers.sh:154`）会按
> `OPENTALKING_FFMPEG_BIN` → PATH 里的 `ffmpeg` → imageio-ffmpeg 二进制 的顺序自动解析，
> 并 export 成 `OPENTALKING_FFMPEG_BIN`，所以 DashScope STT 能正常找到 ffmpeg。
>
> 但**绕过 launcher 直接调用适配器**（自己写脚本、跑单测、用 CLI）时，`_ffmpeg_bin()`
> 只读环境变量不回退 imageio，会抛 `FileNotFoundError: 'ffmpeg'`。
> 为了这两种场景都能跑，已把 venv 内 imageio 的静态 ffmpeg 软链到 `~/.local/bin/ffmpeg`
> （`scripts/11_fix_ffmpeg.sh`，已执行，可重复执行）。

## 二、三阶段部署路线

| 阶段 | 模型 | 是否需要权重 | 用途 |
| --- | --- | --- | --- |
| 1 | `mock` | 否 | 10 分钟跑通 前端 + API + LLM + TTS + WebRTC 全链路 |
| 2 | `wav2lip`（local） | 是，`wav2lip384.pth` 实测 2.0 GB（完整训练 checkpoint，含 optimizer）+ `s3fd.pth` 86 MB | **本机推荐落地形态**：图片/视频形象 + 口型同步，8 GB 显存可用 |
| 3 | `quicktalk`（local） | 是，官方未给直链，需自行获取 | 口型更自然、动作来自模板视频；8 GB 显存需降分辨率，风险较高 |

MuseTalk / FlashTalk / FlashHead / FasterLivePortrait 需要 12 GB+ 显存或 OmniRT 多卡服务，
本机不作为首选。

## 三、常用命令

全部在 **WSL** 里执行（PowerShell 里用 `wsl -d Ubuntu -- bash <脚本路径>` 进入）。

```bash
# 依赖安装 / 续传（可反复执行）
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/03_sync.sh

# 状态自检（依赖进度、服务健康、显存）
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/99_status.sh

# ffmpeg 修复（DashScope STT 必需；系统未装 ffmpeg 时跑一次）
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/11_fix_ffmpeg.sh

# 阶段 1：Mock 链路
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/10_start_mock.sh

# 阶段 2：Wav2Lip 真实渲染（先跑 20_prepare_wav2lip.sh 下权重）
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/20_prepare_wav2lip.sh
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/21_start_wav2lip.sh

# 停止
wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/98_stop_all.sh
```

启动后浏览器打开 <http://localhost:5173>，API 健康检查 <http://localhost:8210/health>。

## 四、四项能力怎么配

> 人设、声音、形象、知识库由你自己导入。**具体操作、格式与接口见 [docs/导入指南.md](docs/导入指南.md)**，本节只说明机制与选型。

### 1) 形象（Avatar）

- 资产目录：`examples/avatars/<avatar-id>/`，必须位于 `OPENTALKING_AVATARS_DIR` 下。
- 两条路径：
  - **WebUI 上传图片**（最快）：形象库 → 从本地上传新形象 → 选基础 Avatar → 传图（≤10 MB，正脸、光照均匀、背景干净）。
  - **脚本预处理视频**（推荐讲解员用，动作更自然）：
    `scripts/prepare_wav2lip_video_asset.py` 抽帧 + 生成 `manifest.json` / `preview.png` / `frames/`。
- 仓库自带 20 个现成形象（`examples/avatars/`），其中 `woman`（职场女/动态，125 帧 858×1072）、
  `office-woman`、`newscaster`、`anchor` 比较适合讲解场景，可直接先用。
- 换成你的讲解员：录 20–40 秒正脸讲解视频（头部动作别太大、姿态自然带轻微手势），用预处理脚本生成资产。

### 2) 声音（Voice / TTS）

- 默认 **Edge TTS**，免 API Key：`zh-CN-XiaoxiaoNeural`（女声，亲和）。
  可选 `zh-CN-XiaoyiNeural`、`zh-CN-XiaohanNeural` 等。
- 想要"专属声音"（景区自己的讲解员音色）：
  - `local_cosyvoice`（本地、可零样本克隆，需另下权重 + 独立 sidecar venv，显存紧张）；
  - `xiaomi_mimo` 音色克隆（API，最省事）；
  - `dashscope` Qwen-TTS（API，音色稳定）。
- 声音在 WebUI 会话里可切换，也可用 `.env` 里的 `OPENTALKING_TTS_DEFAULT_PROVIDER` 固定。

### 3) 知识库（LightRAG）

- 素材放 `OPENTALKING_AGENT_KNOWLEDGE_ROOT`（默认 `./data/knowledge`），WebUI「资产库/知识材料」上传。
- 本项目 `knowledge/` 目录就是讲解词源文件（Markdown 分主题），上传后由 LightRAG 建索引，
  会话级可选择启用哪些材料。
- 检索模式 `hybrid`；embedding 默认 `text-embedding-v4`（1024 维，需 DashScope Key）。
- 讲解类知识库写法：一景点一节、先结论后细节、保留数字与专有名词、避免长表格。

### 4) 动作（手势 / 姿态）

这是最容易误解的一点，先说结论：

> OpenTalking 的 talking-head 模型**不生成骨骼动画**，它按音频驱动口型。
> 画面里的**手势与姿态来自"驱动/模板视频"本身**。

所以做"讲解时带手势"只有三条路：

| 做法 | 模型 | 说明 | 本机可行性 |
| --- | --- | --- | --- |
| 模板视频带手势 | `wav2lip` / `quicktalk` | 讲解员视频里本身有手势，抽帧后输出保留这套动作 | ✅ 推荐 |
| 摄像头/视频实时模仿 | `fasterliveportrait`（OmniRT） | 你自己在镜头前做动作，实时驱动照片形象 | ❌ 需 OmniRT + 多卡 |
| 多段形象轮播 | 任意 | 按讲解段落切换不同动作的 avatar 资产 | ✅ 低成本折中 |

## 五、目录说明

```
digital-human/
├── README.md                  # 本文件
├── config/env.scenic          # 景区讲解专用环境变量（LLM/TTS/STT/知识库/形象）
├── docs/部署手册.md            # 详细步骤、参数、排错
├── knowledge/                 # 你的讲解词源文件放这里，再上传到知识库
├── persona/                   # 你的 Persona 包（.otpersona / .zip）放这里
└── scripts/                   # 01 环境 / 03 装依赖 / 10 Mock / 2x Wav2Lip / 98 停止 / 99 状态
```

WSL 内的运行目录（代码、venv、权重，勿放 `/mnt/d`）：

```
~/opentalking-workspace/
├── opentalking/     # 源码 + .venv
└── models/          # 权重（wav2lip、quicktalk…）
```
