# Git 协作指南（digital-human 部分）

本目录位于 `ren-yi-NUDT/Xiao-Juan` 仓库的 `digital-human/`。
仓库根目录是「小卷机器人」主程序，本目录是「景区讲解数字人」部署工作台，二者在同一仓库里独立演进。

## 一、第一次拿到仓库

```powershell
git clone https://github.com/ren-yi-NUDT/Xiao-Juan.git
cd Xiao-Juan
```

> 国内网络如果 `git clone` 卡住，多半是 git 配了没启动的代理（例如 `127.0.0.1:7897`）：
>
> ```powershell
> git -c http.proxy= -c https.proxy= clone https://github.com/ren-yi-NUDT/Xiao-Juan.git
> ```
>
> 想把代理设置永久去掉：`git config --global --unset http.proxy; git config --global --unset https.proxy`

## 二、每次改之前

```powershell
cd D:\项目\xiao_juan\Xiao-Juan
git checkout lmam        # 或你要基于的分支
git pull
git checkout -b 你的分支名
```

分支命名建议：

| 场景 | 分支名示例 |
| --- | --- |
| 改讲解词 / 知识库 | `kb/lingshan-update` |
| 改部署脚本 | `fix/wav2lip-memory` |
| 加人设形象 / 音色 | `feat/avatar-voice` |
| 改文档 | `docs/manual` |

## 三、提交

```powershell
git status                       # 看改了什么
git add digital-human            # 只提交你这个目录
git commit -m "简短说明：改了什么、为什么"
git push -u origin 你的分支名
```

commit message 写法：`动词: 内容`，例如

- `docs: 补充自定义形象与音色章节`
- `kb: 修正灵山大佛铜量数据`
- `fix: 脚本改为相对路径定位`

## 四、合并到主干

在 GitHub 网页上对你的分支发起 Pull Request，目标分支选 `lmam`（或团队约定的主干）。
至少一位组员 review 后再 merge。**不要直接往 `lmam` 强推。**

## 五、绝对不要提交的东西

`digital-human/.gitignore` 已经挡掉了下列内容，但提交前仍建议看一眼 `git status`：

| 文件 | 原因 |
| --- | --- |
| `config/env.scenic` | 含真实 API Key。要分享配置就复制成 `config/env.scenic.example` 并把 Key 换成占位符 |
| `素材/`、`*.mp4`、`*.wav`、`*.mp3` | 体积大，进 git 会永久留在历史里，clone 会变慢 |
| `*.log`、`*.pid`、`.venv/`、`__pycache__/` | 运行产物 |

**万一把 Key 提交上去了**：立刻去百炼控制台吊销并重建 Key，光删文件没用——git 历史里还在。
清理历史需要用 `git filter-repo`，比换 Key 麻烦得多。

## 六、WSL 侧注意事项

- 所有部署脚本要在 WSL 里跑：`wsl -d Ubuntu -- bash /mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/21_start_wav2lip.sh`
- 脚本已经从**自身位置**推导项目根目录，所以整个 `Xiao-Juan` 目录挪到别处不需要改脚本
- 但 `config/env.scenic` 是本机私有文件、不随仓库走：新机器上从 `env.scenic.example` 复制一份，
  填自己的 Key 和路径后再启动
- `.gitattributes` 规定 `*.sh` / `*.py` / `*.md` 用 LF，避免 Windows 换行导致 `bash: $'\r': command not found`

## 七、常用地址

| 用途 | 地址 |
| --- | --- |
| 仓库 | https://github.com/ren-yi-NUDT/Xiao-Juan |
| 本目录 README | https://github.com/ren-yi-NUDT/Xiao-Juan/tree/lmam/digital-human |
| Pull Requests | https://github.com/ren-yi-NUDT/Xiao-Juan/pulls |
| 百炼控制台（Key / 充值） | https://bailian.console.aliyun.com/ |
