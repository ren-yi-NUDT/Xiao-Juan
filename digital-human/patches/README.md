# OpenTalking 源码补丁（2D 形象支持）

`digital-human/` 是配置/文档/脚本目录，OpenTalking 本体在 WSL 的 `~/opentalking-workspace/opentalking`（独立 git 仓库，remote 指向上游 `datascale-ai/opentalking`）。

本目录保存了让 OpenTalking 支持 2D 分层形象所需的源码改动副本，方便组内其他人复现环境。

## 改动文件（共 6 个）

| 文件 | 作用 |
| --- | --- |
| `apps/web/src/components/Light2dAvatar.tsx` | 扩展渲染：head/arms 图层叠加、动作状态机、字幕接线、听你说话时待机 |
| `apps/web/src/components/SceneStage.tsx` | 把字幕文本传给 Light2dAvatar（用于关键词触发） |
| `apps/web/src/light2d/config.ts` | 解析 avatar.json 的 head/arms 图层与 extensions 配置（向后兼容旧配置） |
| `apps/web/src/light2d/actions.ts` | 新增：动作状态机纯函数（关键词匹配/分句/随机） |
| `apps/web/tests/actions.test.ts` | 新增：状态机单测 |
| `opentalking/avatar/light2d.py` | 后端：把扩展图层纳入 client-assets 白名单（否则图层 404） |

## 安装方法

新组员克隆本项目后，跑一键安装脚本（会同时安装源码补丁 + 形象配置 + 27 张图层）：

```powershell
wsl -d Ubuntu -- bash "/mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/40_install_2d_patches.sh"
```

它做的事等价于手动：
- 把 `patches/opentalking/` 下的 6 个源码文件覆盖到 OpenTalking 仓库
- 把 `config/avatar-2d/` 的配置（manifest/avatar.json/预览图）放到 `examples/avatars/lingshan-guide-2d/`
- 把 `素材/layers/` 的 27 张图层放到同目录的 `light2d/layers/`
- 跑单测 + 类型检查 + 构建

然后重启服务：

```powershell
wsl -d Ubuntu -- bash -lc 'cd ~/opentalking-workspace/opentalking/apps/web && npm test && npx tsc --noEmit && npm run build'
wsl -d Ubuntu -- bash "/mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/98_stop_all.sh"
wsl -d Ubuntu -- bash "/mnt/d/项目/xiao_juan/Xiao-Juan/digital-human/scripts/00_start.sh"
```

## 注意

- 这些改动**不在** `Xiao-Juan` 仓库的 git 跟踪范围内（OpenTalking 是独立仓库），所以以本目录的副本为准
- 形象资产本体（`examples/avatars/lingshan-guide-2d/`）也是 OpenTalking 仓库里的未跟踪目录，
  完整副本已保存在 `digital-human/config/avatar-2d/`（配置+预览图）和 `digital-human/素材/layers/`（27 张图层），
  一键安装脚本会自动复制过去
- 上游 OpenTalking 升级后这些补丁可能需要重新适配；改动都集中在 Light2D 相关文件，冲突面较小
