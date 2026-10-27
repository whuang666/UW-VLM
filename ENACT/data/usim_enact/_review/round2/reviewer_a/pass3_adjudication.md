# Pass 3 裁决（reviewer_a · A 组 usim_train_episode_000200/000201/000552）

复核日期：2026-10-27（Asia/Shanghai）。
Pass 1（盲评）先写盘并锁定（`pass1/pass1_lock.json`），随后才读取 `annotations/episodes/*.json`；本文件是 Pass 2 的 8 个硬分歧 + 4 个 OnSeabed 中止项 + 4 个可疑点的物理裁决。

## 0. 证据与方法

| 证据 | 说明 | 路径 |
|---|---|---|
| ego 视频上下文 | 关键帧 ±15/±30/±60 帧接触表（每个偏移取解码帧；因视频是"渲染保持式"，同画面会重复） | `pass3/context/ego_ctx_<ep>_<frame>.png` |
| wrist 视频上下文 | 同帧位 wrist 视角接触表（夹爪特写，用于接触/距离裁决） | `pass3/context/wrist_ctx_<ep>_<frame>.png` |
| 唯一画面时间线 | ego 每 8–14 帧才更新一个渲染画面：343 帧只有 42 个唯一画面（ep200）、368→35（ep201）、374→38（ep552）；wrist 分别 82/33/53 个唯一画面 | `tools_out/unique/ep*/`、`pass3/wrist_unique/ep*/` |
| 夹爪信号（辅助） | parquet `observation.state[0]`，阈值 0.004，~3 帧 ramp；close 事件：ep200 f228、ep201 f259、ep552 f264；无 open 事件（episode 结束时仍夹持） | `pass3/signals.json` |
| 离底高度（辅助） | parquet `observation.state[28]` = DVL altitude `dvl_h`；`state[27]` = pressure（海面以下压力，随深度同向变化） | `pass3/signals.json` |

**关键统计（辅助信号，不作真值）**：三条 episode 的 key3 都落在 dvl_h 最低点，上浮起点（dvl_h 比 close 后最小值高 2 cm 的首帧）分别在 close 后 43/42/42 帧（f271/f301/f306）；key4 时 dvl_h 分别比最低点高 **16.3 / 16.4 / 16.9 cm**。即：**key3 时载具尚未上浮，key4 时已明显上浮**。

> 注意：ego 视频大量完全重复帧（每 8–14 帧更新一次内容），所以"±15 帧邻域"常常只是一两个不同画面；用"唯一画面时间线"复核比等距抽帧更可靠。

## 1. 逐项裁决表

裁决口径：`original_ok` = 物理证据支持 v0.1 原值；`review_ok` = v0.1 原值不成立/无证据、复核意见被采纳；`both_acceptable` = 取决于定义、两种读法都可自圆其说；`undecidable` = 证据不足以裁决。**本组没有 undecidable 项，但有 7 项是"定义问题"而非"视觉问题"。**

| ID | episode/frame | 关系 | 原值 | 复核 | 裁决值 | 裁决 | 依据（简） |
|---|---|---|---|---|---|---|---|
| D01 | 200 / f140 | NextTo | false | true | 阶段语义 false / 几何语义 true | **both_acceptable** | wrist f136–145：夹爪与物体之间仍有可见空隙（~10–15 px），机器人未到达物体；ego 的"接触"是透视遮挡。按"到达抓取位姿前"是 false，按纯距离是 true。 |
| D02 | 200 / f248 | NextTo | false | true | 阶段语义 false / 几何语义 true | **both_acceptable** | wrist f246–259：已夹紧，机器人末端与物体距离≈0；v0.1 的 false 只可能是"生命周期阶段"语义。 |
| D03 | 200 / f328 | NextTo | false | true | 同上 | **both_acceptable** | wrist f314–342：夹持并上浮，末端与物体仍最近。 |
| D04 | 201 / f279 | NextTo | false | true | 同上 | **both_acceptable** | wrist f268–287：close(f259) 后夹紧。 |
| D05 | 201 / f357 | NextTo | false | true | 同上 | **both_acceptable** | wrist f348–367：夹持 + 上浮 ~16 cm。 |
| D06 | 552 / f120 | NextTo | false | true | **false** | **original_ok** | wrist f110–123：红圆柱在画面右侧、与夹爪口部相距 ~40–50 px，机器人尚未到达；pass1 的 true 是 ego 深度压缩造成的误读。 |
| D07 | 552 / f284 | NextTo | false | true | 阶段语义 false / 几何语义 true | **both_acceptable** | wrist f260–313：close(f264) 后夹紧。 |
| D08 | 552 / f364 | NextTo | false | true | 同上 | **both_acceptable** | wrist f356–373：夹持 + 上浮 ~17 cm。 |
| S01 | 200 / f213 | OnSeabed | true | undecidable | **true** | **original_ok** | dvl_h 0.266（接近最低 0.235，上浮未开始）；wrist f204–225 物体进入夹爪口但未合拢、无竖直提升；物体此前立在海床上。ego 不可判 ≠ 原值错。 |
| S02 | 200 / f248 | OnSeabed | false | undecidable | **unknown（物理倾向 true）** | **review_ok** | dvl_h 已到最低点 0.235、上浮起点 f271；wrist f246–259 夹紧后物体相对夹爪无竖直位移 → 无离底证据，物体极可能仍接触海床。"false"来自模板推导。 |
| S03 | 201 / f279 | OnSeabed | false | undecidable | **unknown（物理倾向 true）** | **review_ok** | dvl_h=0.2313 最低点，上浮起点 f301；相对 key2（0.2848）还下降 5 cm。 |
| S04 | 552 / f284 | OnSeabed | false | undecidable | **unknown（物理倾向 true）** | **review_ok** | dvl_h=0.2597 最低点，上浮起点 f306。 |
| X01 | all / key4 | Lifted | true | true | **true** | **original_ok** | dvl_h +16.3/+16.4/+16.9 cm、pressure 同向下降；ep201 wrist 背景由沙面变水体。值对，但 ego-only 单帧弱。 |
| X02 | all / key2→key3 | InGripper | false→true | false→true | **true** | **original_ok** | close 帧 228/259/264；key2 在 close 前 15 帧、key3 在 close 后 16–20 帧；wrist 包夹关系由张开变夹紧。 |
| R01 | 200 / 213→248 | 动作文本 | 见下 | — | 需重写 | **review_ok** | 文本同时含 `grasped` 与 `no longer next to`，且 `no longer on the seabed` 无可见证据（S02）。 |
| R02 | 200 / 140→213 | 动作文本 | 见下 | — | 需重写 | **review_ok** | ego 可见变化是物体被拨倒，而文本写"robot becomes next to"；同文本在 ep201/ep552 才与可见变化大致相符。 |
| R03 | all 7 episodes | 标注方式 | — | — | 需逐帧重标 | **review_ok** | 7 条 episode 的 4×4 事实表完全相同，动作文本除对象名逐字相同 → 模板套用，非逐帧证据。 |
| R04 | 200/201 notes | 对象说明 | "red cylinder" | — | 应为 red fish | **review_ok** | wrist 视角显示红色物体由远及近再离开、姿态剧变 = 游动小鱼。 |
| X03 | 200 | 与 qwen3.8-max 3 处错误的关系 | — | — | — | **review_ok** | 3 处图像条件错误全部在 ep200，且恰好是 213/248 顺序与 248→328 lift 映射两类最弱环节。 |

裁决分布：8 个硬分歧 → **both_acceptable 7、original_ok 1**；全部 19 项 → **original_ok 4、review_ok 8、both_acceptable 7、undecidable 0**。

## 2. 三条核心结论

1. **8 个硬分歧全部是 NextTo，且 7 个是定义问题，不是视觉判断分歧。** v0.1 的 NextTo 实际语义 ≈"机器人已到达抓取位姿但尚未夹紧"（key1 未到达=false、key2 已到达=true、key3/4 已夹紧=false）；名字与语义不符，编译出的动作文本把"阶段变化"写成了"空间关系变化"。
2. **key3 的 `OnSeabed=false` 没有物理证据。** 三个 key3 帧的 dvl_h 都在最低点、上浮尚未开始，夹爪只是合拢、没有提升；物体极可能仍然接触海床。该 false 是"grasped ⇒ 不再 on seabed"模板推导出来的。ego 单帧也无法判定（pass1: undecidable）。
3. **真实的 3 处模型错误（qwen3.8-max）全部落在本组 ep200 的这两个薄弱环节上**（NextTo/抓取前阶段、Lifted 可见性），因此 0.9571 的残差不能简单归因于模型能力；v0.2 应先修标签/定义，再评估模型。

## 3. 与 v0.1 原值的对照汇总（仅本组）

- 48 个"帧×关系"判定：一致 36、复核放弃（undecidable）4、硬分歧 8（全部为 NextTo）。
- 逐谓词：`InGripper` 12/12、`Lifted` 12/12、`OnSeabed` 8/12（4 项 undecidable，0 硬分歧）、`NextTo` 4/12。
- 9 个相邻转移：v0.1 全部非空（模板保证）；仅 2 个能"仅凭 ego 直接辨认"（ep201 199→244、ep552 120→249 的距离变化），其余 7 个依赖 NextTo 阶段语义或 ~16 cm 的 Lifted 上浮（ego 单帧弱）。

## 4. NextTo "approach 语义"自洽性证据链（应 Lead 要求补充）

**问题**：v0.1 的 NextTo 在抓住后置 false。Lead 已判定这是**语义定义问题而非标签错误**。本节给出"v0.1 在 approach 语义下自洽、但文档必须显式写明定义"的证据链，并回答"是否还有帧在 approach 语义下也应为 true"。

### 4.1 定量事实（三条 episode 完全同构）

| 事件 | ep200 | ep201 | ep552 |
|---|---|---|---|
| key1 帧 | f140 | f199 | f120 |
| key2 帧 | f213 | f244 | f249 |
| key3 帧 | f248 | f279 | f284 |
| key4 帧 | f328 | f357 | f364 |
| 夹爪 close 事件 | f228 | f259 | f264 |
| **key2 = close − 15 帧** | f213 = 228−15 | f244 = 259−15 | f249 = 264−15 |
| **key3 = close + 20 帧** | f248 | f279 | f284 |
| key1 = close − 88 / −60 / −144 帧 | 88 | 60 | 144 |
| wrist 显示"物体进入夹爪口部"的时刻（到达抓取位） | ≈f161（run 160 起） | ≈f228–247 | ≈f198–199 |
| 上浮起点（dvl_h 最低点后 +2 cm） | f271 | f301 | f306 |

### 4.2 证据链：v0.1 的 NextTo 序列 = "到达抓取位（尚未夹紧）"阶段

1. **key2 恰好都是 close−15**，且 wrist 显示该时刻物体已进入夹爪口部、夹爪尚未合拢（ep200 f213 在到达时刻 f161 之后；ep201 f244 在 ≈f228 之后；ep552 f249 在 ≈f199 之后）。
2. **key1 都在到达抓取位之前**：ep200 f140 时 wrist 显示夹爪与物体之间仍有可见空隙（≈10–15 px），到达发生在 f161 附近，故 f140 属"接近途中"而非"已到位"；ep201 f199 物体距离夹爪 >90 px（ego）；ep552 f120 的 wrist 图显示物体在右侧、与夹爪相距 ≈40–50 px，到达要等到 ≈f199。
3. **key3/key4 都在夹紧之后**（key3 = close+20；key4 在末段），按 approach 语义恒为 false。
4. 因此 v0.1 的三条 episode 都精确呈现 `key1=false → key2=true → key3=false → key4=false`，**与"approach 阶段只在'到达抓取位、尚未夹紧'这一窗口内为 true"的定义自洽**。

### 4.3 "是否还有帧在 approach 语义下也应为 true"

| 帧 | 若定义 = **到达抓取位窗口**（推荐） | 若定义 = **单纯接近/近距离**（不推荐） | 结论 |
|---|---|---|---|
| ep200 f140 | false（尚未到达，arrival≈f161） | **true**（末端已很近、未抓住） | 边界帧：两种定义会给出相反值；v0.1=false 只在"到达窗口"定义下自洽 |
| ep200 f213（key2） | true | true | 一致 |
| ep201 f199（key1） | false（距离 >90 px） | false | 一致 |
| ep201 f244（key2） | true（已接近/到达口部） | true | 一致 |
| ep552 f120（key1） | false（wrist 相距 ≈40–50 px，离 close 还有 144 帧） | false（仍属远处接近） | 一致，v0.1 正确 |
| ep552 f249（key2） | true | true | 一致 |

- **ep552 f120：v0.1 的 false 在两种读法下都成立**（wrist 证据：距离大、到达还早），不是标签错误。
- **ep200 f140：是唯一边界帧**。在"到达窗口"定义下 false 自洽；在"末端已靠近且未抓住"的宽口径 approach 定义下应为 true。v0.1 的 false 能被解释为"该帧尚未进入抓取位姿窗口"，但**文档没有写这条边界**，所以从外部看就是一处不可复核的语义跳跃。
- 除 f140 外，**12 个关键帧中没有任何一帧需要改判**：只要 v0.2 把 NextTo 显式定义为"approach（到达抓取位、尚未夹紧；抓住后恒 false）"，v0.1 的三条序列(key1 F / key2 T / key3 F / key4 F)可整体作为历史数据保留，但必须在文档注明定义，且不能把 NextTo 当纯几何距离使用。

### 4.4 对 v0.2 的可执行建议

1. 在规范中写明：`NextTo` = **approach**（机器人末端进入"抓取位姿窗口"、尚未夹紧）；抓取后恒 false；不是纯距离。
2. 给出可复核的窗口边界（建议二选一并在 notes 记录）：
   - **(推荐)** 事件锚定：`NextTo=true` 只取 close 事件前 15±5 帧内、且 `InGripper=false`、`OnSeabed=true` 的稳定帧（本组 3 条 episode 的 key2 全部精确落在 close−15）；
   - 或者距离锚定：给出 ego/wrist 上可量的阈值并验证，但 ego 深度压缩不可靠，不如事件锚定。
3. 动作文本生成器同步修改：一旦 `NextTo` 采用 approach 语义，transition 2 的文本必须写成"机器人闭爪夹住仍贴在海床上的物体"，不能再出现 "grasped + no longer next to" 的矛盾句。
4. `Touching` 若启用（L=5 touching 路线），同样需要事件锚定（close 前、物体仍在海床、可见接触），否则会与 NextTo 混淆。

