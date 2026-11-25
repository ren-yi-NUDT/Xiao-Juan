# 分层立绘素材生成 Prompt（数字人「讲解员小景」）

> 用途：给支持文生图 / 参考图一致性 / 透明背景的 AI 画图工具（Midjourney、SDXL、即梦、通义万相、GPT Image 等）使用。
> 目标：产出一套 **可分层切换** 的 2D 全身立绘，供项目 `Light2D` 渲染器做「待机动作随机轮播 + 讲解动作随机穿插 + 关键词触发」。
> 核心难点不是单张图好看，而是 **所有图层必须是同一个人物、同一套比例、同一坐标系**。务必先做第 1 步的角色参考图，后面每一张都挂载它做参考。

---

## 0. 生成流程（必须按顺序）

1. **先生成"角色参考图"**（第 2 节 Master Prompt），直到你满意为止。这张图定死人物的脸、发型、服装、配色、画风。
2. 之后每一层素材，都要 **以参考图为参考（character reference / img2img / seed 固定）**，并在 prompt 开头粘贴第 3 节的「通用前缀」。
3. 逐张生成 → 检查锚点 → 按第 5 节命名 → 放到 `assets/avatar-lingshan/layers/`。
4. 全部生成后我可以写脚本自动转 PNG、去背、对齐锚点、生成 `avatar.json`，并接入状态机。

**强烈建议**：先在画图工具里固定同一个 seed / 同一个角色 LoRA / 同一张参考图，否则 30 多张图会出现"脸每张三样"的问题。

---

## 1. 画布与锚点规范（技术硬约束，写进每张图的 prompt）

| 项 | 值 |
| --- | --- |
| 画布尺寸 | **1024 × 1536 px**（竖版 2:3），所有图层必须同尺寸 |
| 背景 | **纯透明（RGBA alpha=0）**，不要任何背景、地面、阴影、渐变底板 |
| 人物范围 | 头顶 y≈80，鞋底 y≈1460，左右不超出 x∈[80, 944] |
| 头部中心 | (512, 260)，头宽约 220、头高约 280 |
| 左眼中心 | (450, 275)；右眼中心 (574, 275) |
| 嘴中心 | (512, 340) |
| 左肩 | (400, 470)；右肩 (624, 470) |
| 腰部 | (512, 820) |
| 双手自然垂放位置 | 左手 (380, 900)，右手 (644, 900) |
| 脚底 | (512, 1460) |
| 光源 | 左上 45° 柔光，统一，不要每张图换光 |
| 线条 | 深色细描边（深棕黑 #2A2422），线宽一致 |
| 上色 | 扁平赛璐璐，2–3 阶阴影，无渐变、无纹理噪点、无写实皮肤质感 |

**给画图 AI 的话术**：`same canvas 1024x1536, transparent background, character anchored at exactly the same position and scale as the reference, full body visible, no cropping, no ground shadow, consistent lighting from upper left`

---

## 2. Master Prompt：角色参考图（中文版）

先只生成这一张，确认满意后再往下走。

```
日系二次元动画风格全身立绘，30岁成年女性景区讲解员，黑色齐肩短发（发尾微内扣，中分刘海），
戴黑框方形眼镜，温和干练的表情，浅微笑，职业装：白色衬衫 + 藏青色西装外套 + 藏青色及膝西装裙，
肉色丝袜，黑色皮鞋，胸前佩戴小巧工牌。
站姿端正、从容，双手自然垂在身体两侧，正面全身，头到脚完整入镜。
干净扁平赛璐璐上色，深棕黑细描边，左上45度柔光，2阶阴影。
主色：白、藏青、浅金（工牌与纽扣点缀）、黑框眼镜。
背景：纯透明（或纯白，仅作参考图，最终素材必须透明）。
画布 1024x1536，人物居中，头顶 y=80，鞋底 y=1460。
角色设定参考图 / character sheet，正面全身站姿。
```

**English version（多数画图模型更吃英文）：**

```
Full-body character reference sheet, Japanese anime style, a 30-year-old female scenic-area tour guide.
Black shoulder-length bob hair with slightly inward-curled ends, center-parted bangs.
Black rectangular-framed glasses. Gentle, capable, professional expression with a faint smile.
Business attire: white dress shirt, navy blazer, navy knee-length pencil skirt, beige tights, black leather heels.
A small employee badge pinned on the chest. Upright, composed standing pose, arms relaxed at sides.
Flat cel shading, clean thin dark-brown-black outlines (#2A2422), soft lighting from upper-left,
2-tone shadows, no gradients, no realistic skin texture.
Palette: white, navy blue, light gold accents (badge and buttons), black glasses.
Transparent background (or plain white for the reference only). Canvas 1024x1536.
Full figure head-to-toe, centered, head top at y=80, shoe soles at y=1460.
Consistent character design, front-facing full-body standing pose.
```

---

## 3. 每层的通用前缀（每张图都要粘贴在 prompt 最前面）

```
【通用前缀 · 每张素材都加】
同一个角色（严格使用参考图里的脸型、五官、发型、眼镜、服装、配色、描边和画风），
画布 1024x1536，透明背景，人物锚点与参考图完全一致、比例完全一致，
全身完整入镜不裁切，左上45度同一光源，扁平赛璐璐上色，深棕黑细描边，2阶阴影，
不要背景、不要地面、不要投影、不要多余物体，只画下方指定的部位/姿势。
```

英文：
```
SAME character as reference (identical face, hairstyle, glasses, outfit, palette, line weight and art style),
canvas 1024x1536, transparent background, character anchored at exactly the same position and scale as reference,
full body in frame, no cropping, same upper-left lighting, flat cel shading, thin dark outlines,
no background, no ground, no shadow, no extra objects. Only draw the specified part/pose below.
```

---

## 4. 分层清单与逐张 Prompt

图层顺序（从下到上）：`body` → `head_*` → `eyes_*` → `mouth_*` → `arms_*`

### 4.1 身体底图（1 张）

**`body.png`**
```
【通用前缀】
只画身体：白衬衫 + 藏青西装外套 + 藏青及膝裙 + 肉色丝袜 + 黑色皮鞋 + 胸前工牌。
不要头部、不要手臂、不要脸、不要眼睛、不要嘴。
肩线在 y=470，腰部 y=820，脚底 y=1460，双手自然垂放位置留出空位（手臂图层后续叠加）。
从脖子根部（y≈450）往下画，站姿端正。
```

### 4.2 头部变体（4 张）

**`head_center.png`**
```
【通用前缀】
只画头部：黑色齐肩短发、中分刘海、黑框方眼镜、脸部皮肤、鼻子、耳朵。
不要眼睛、不要眉毛、不要嘴（这些是独立图层）。
头部中心 (512,260)，宽约220、高约280，正面朝向。
```

**`head_left.png`**
```
【通用前缀】
只画头部，和 head_center 完全相同，但头 (512,260) 整体缓慢转向自己的左侧约20度，
眼睛/嘴仍留空，发型和眼镜跟着透视变化，脸部朝向偏左。
```

**`head_right.png`**
```
【通用前缀】
只画头部，和 head_center 完全相同，但头整体转向自己的右侧约20度，
眼睛/嘴留空，发型眼镜跟随透视。
```

**`head_tilt.png`**
```
【通用前缀】
只画头部，和 head_center 完全相同，但头微微歪向一侧约12度（思考状），
眼睛/嘴留空，发型眼镜跟随倾斜。
```

### 4.3 眼睛（2 张）

**`eyes_open.png`**
```
【通用前缀】
只画睁开的双眼 + 眉毛，位于左眼(450,275)、右眼(574,275)。
透过黑框眼镜可见，温和干练的大眼，瞳孔高光。不要画脸、头发、嘴。
```

**`eyes_blink.png`**
```
【通用前缀】
只画闭合的双眼（一条弯弧线）+ 眉毛，位置与 eyes_open 完全一致。
透过黑框眼镜可见，闭眼自然。不要画脸、头发、嘴。
```

### 4.4 嘴型（4 张，口型同步用）

**`mouth_0.png`**（闭合/静音）
```
【通用前缀】
只画闭合的嘴，位置 (512,340)，一条自然的浅微笑细线，不要牙齿。
```
**`mouth_1.png`**（小开口）
```
【通用前缀】
只画微微张开的嘴，位置 (512,340)，小幅椭圆开口，露出少量上齿。
```
**`mouth_2.png`**（中开口）
```
【通用前缀】
只画中等张开的嘴，位置 (512,340)，椭圆开口，可见上下齿。
```
**`mouth_3.png`**（大开口）
```
【通用前缀】
只画明显张开的嘴，位置 (512,340)，较大开口，可见牙齿和舌，说话夸张口型。
```

### 4.5 手臂/姿势叠加层（16 张）

> 全部只画**双臂+手**（必要时含一点袖口），从肩点 (400,470)/(624,470) 出发。
> 不要画身体、头、腿、脸。透明背景。所有图层必须与身体锚点严丝合缝。

**待机类（7 张）**

| 文件名 | Prompt（接【通用前缀】后） |
| --- | --- |
| `arms_idle_breath.png` | 双臂自然垂在身体两侧，手掌轻贴裙侧，最基础的放松站姿手臂 |
| `arms_idle_look_left.png` | 双臂自然垂放，头虽转但手臂保持放松，肩线略随头部左转 |
| `arms_idle_look_right.png` | 同上，肩线略随头部右转 |
| `arms_idle_glasses.png` | 右手抬起，食指轻扶黑框眼镜边缘（约在脸右侧 y=260），左手自然垂放 |
| `arms_idle_behind.png` | 双手背到身后，右手握左手腕，肩稍后展，显从容 |
| `arms_idle_clasp.png` | 双手在身前轻握交叠，位置约 (512,880)，手背朝向观众 |
| `arms_idle_shift.png` | 双臂自然垂放，但重心偏右，左肩略低右肩略高，身体微倾 |

**讲解类（9 张）**

| 文件名 | Prompt（接【通用前缀】后） |
| --- | --- |
| `arms_speak_neutral.png` | 双手在身前自然小幅摆动，右手略前伸、左手略后，讲解中的放松手势 |
| `arms_speak_point.png` | 右手向观众左侧前方伸出，食指明确指向侧前方，手臂约与肩同高，左手自然垂放 |
| `arms_speak_welcome.png` | 右手抬起至肩高，手掌张开向观众轻挥（招呼手势），左手自然垂放 |
| `arms_speak_emphasize.png` | 双手摊开在身体两侧略前，掌心向上微朝观众，强调语气 |
| `arms_speak_think.png` | 右手抬起轻托下巴（思考状），手肘自然下垂，左手自然垂放 |
| `arms_speak_measure.png` | 双手在身前比划一个较大的高度/宽度，掌心相对分开约 60cm 距离感，示意「高大」 |
| `arms_speak_count.png` | 右手竖起食指置于胸前，其余手指微屈，做「第一」数数手势，左手自然垂放 |
| `arms_speak_invite.png` | 右手向侧前方平伸，掌心向上做「请随我来」引导手势，身体微侧 |
| `arms_speak_nod.png` | 双臂自然垂放，肩上抬一点点配合轻微点头（手臂几乎不动，仅肩线配合） |

---

## 5. 命名与交付

```
assets/avatar-lingshan/layers/
├── body.png
├── head_center.png / head_left.png / head_right.png / head_tilt.png
├── eyes_open.png / eyes_blink.png
├── mouth_0.png / mouth_1.png / mouth_2.png / mouth_3.png
└── arms_idle_breath.png ... arms_speak_nod.png   (16 张)
```

要求：
- 全部 **1024×1536 RGBA PNG**，透明背景
- 每张图人物位置/大小与参考图**逐像素对齐**（我这边会用脚本按锚点再校准一次）
- 不要一张图里塞多个姿势；不要画背景；不要文字水印

---

## 6. 验收清单（你交付前自查）

- [ ] 30 张左右素材人脸/发型/眼镜/服装/配色完全一致（像同一个人）
- [ ] 所有图同一画布 1024×1536、透明背景
- [ ] 头部中心始终 (512,260)，肩点 (400,470)/(624,470)，脚底 (512,1460)
- [ ] 眼睛/嘴是独立图层，头图上没有眼睛和嘴
- [ ] 手臂图层不含身体/头/腿
- [ ] 没有背景、地面、阴影、多余物体

---

## 7. 我这边接下来会做的事（素材到位后）

1. 写脚本把 PNG 按锚点对齐、统一尺寸、去毛边
2. 生成 `assets/avatar-lingshan/light2d/avatar.json`：图层 z 序、锚点、嘴型映射、眨眼周期
3. 写动作状态机：待机 7 种随机轮播 / 讲解 9 种随机穿插 / 关键词表触发指定动作 / 按 TTS 分句边界切换
4. 改 `Light2dAvatar.tsx` 或新增一个渲染组件，支持自定义分层素材（现有实现只支持内置 dogo 的固定图层）
5. 用 WebUI 验收：说话时口型+动作、静默时待机动画、关键词触发

---

## 8. 关键词触发表（实现时我会写进状态机，先给你过目）

| 动作 | 触发词（命中任意一个即触发） |
| --- | --- |
| 指引 | 请看、这边、位于、前方、左边、右边、左侧、右侧、沿、往 |
| 欢迎 | 欢迎、大家好、各位游客、欢迎大家 |
| 强调 | 重点、注意、一定、千万、最重要、切记、必须 |
| 思考 | 据说、相传、传说、传说中、据说、让我想想、相传 |
| 比大小 | 高达、米、吨、巨大、宽、高、长、重 |
| 数数 | 第一、第二、第三、首先、其次、最后、一是、二是 |
| 邀请前行 | 请随我、跟我来、往前走、请进、请这边走 |
| 点头 | 对的、没错、是的、可以、正是、的确 |

未命中时：讲解动作在 9 种里随机；待机在 7 种里随机（已删「低头看资料/工牌」）。
