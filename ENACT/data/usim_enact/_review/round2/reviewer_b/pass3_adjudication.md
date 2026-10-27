# Pass 3 — 分歧裁决（reviewer_b / B 组 553/555/556/1302）

日期：2026-10-27（Asia/Shanghai）。对象：`usim-enact-v0.1` 标签 + `blind-review-20261027` 盲评包。
本文件只使用：关键帧 raw/QA 图、ego 视频上下文（±15/30/60 帧接触表）、wrist 视频、parquet
`observation.state[0]`（夹爪信号，原始值约 0.0000=开 / 0.0149=闭）与 `state[27]`（压力/深度代理，仅作辅助）。
证据接触表在 `pass3/*.png`（每格标注帧号、夹爪信号、压力）；辅助信号表在 `pass3/aux_lift_signal.json`。

## 0. 方法与辅助信号摘要（不是真值，只用于裁决）

| episode | 夹爪 close 帧 | open 帧 | close 后压力峰值 | 末段最低 | 辅助"开始上升"帧（峰值下降 10%） |
|---|---:|---:|---:|---:|---:|
| 553 | 149 | — | 12.1293 @149 | 11.9222 | ≈182 |
| 555 | 278 | — | 12.1343 @300 | 11.9490 | ≈320 |
| 556 | 319 | — | 12.1058 @344 | 11.9226 | ≈360 |
| 1302 | 176 | 448 | 2.6309 @178 | 2.1181 | ≈225 |

读法：4 条 episode 的关键帧结构都是 **未抓取（在海底）→ 抓取（未升离海床）→ 保持并上升（Lifted）**。
辅助信号显示"抓取但尚未上升"的中间帧都落在压力峰值附近（553/f168、555/f297、556/f339、1302/f196），
而 `Lifted=true` 的关键帧都落在辅助上升起点之后（553/f248、555/f377、556/f419、1302/f415）。
**这与 v0.1 的 Lifted 标签一致**，说明标签的物理过程判断基本正确；问题在于这些细分状态在 320×240 ego 单帧上的可辨性。

## 1. 关系取值分歧裁决（17 格）

裁决口径：`original_ok`=原标签可接受；`review_ok`=复核值更合理/原标签需改；`both_acceptable`=两种解释都成立（通常是定义问题）；`undecidable`=无法裁决。

| # | episode | frame | 关系 | 原值 | 复核值 | 裁决 | 证据与说明 |
|---:|---|---:|---|---|---|---|---|
| 1 | 553 | 110 | NextTo(robot,cylinder) | false | true | both_acceptable | 定义问题。f110 是 1 帧瞬态，物体被画面下边缘裁切，夹爪在画面上方约 100 px；"接近但未到位"（原标注 false）与"已在交互距离"（复核 true）都可成立。逐帧证据见 `ep000553_f00110_*`。 |
| 2 | 553 | 168 | NextTo | false | true | both_acceptable | 抓住后为 false 只有在该谓词被定义为"抓取前的到位瞬间"时才成立；若按自然"相邻/邻近"读法应为 true。视频确认夹爪已夹住物体（close=149，f168 物体随夹爪移动）。 |
| 3 | 553 | 248 | NextTo | false | true | both_acceptable | 同上；f248 物体被夹持并已升离海床（辅助上升始于 ≈182），"robot 不再 next to 物体"在动作文本中自相矛盾。 |
| 4 | 555 | 140 | OnSeabed | true | undecidable | both_acceptable | 该帧红色像素为 0（目标完全不可见，见 §2），事实无法从该帧验证；但视频连续性显示目标在 f174 后出现且位于海床上、此前未被抓取，故 world state 为 true 可接受。 |
| 5 | 555 | 140 | Lifted | false | undecidable | both_acceptable | 同上，目标不可见；world state false 与视频一致，但该帧无 ego 证据。 |
| 6 | 555 | 140 | NextTo | false | undecidable | both_acceptable | 目标不可见，robot-object 距离无法估计；"false"只是默认/推断值。 |
| 7 | 555 | 297 | OnSeabed | false | undecidable | original_ok（v0.1 语义）/ **review_ok（v0.2 物理支撑语义）** | close=278、f297 已闭合并夹住；从 ±15/30 帧接触表看物体被夹在夹爪上、下方有窄阴影带；辅助压力仍在峰值（未上升）。按 v0.1"抓住即离开海床"的模板，false 可接受；但按 Lead 采纳的 v0.2 物理支撑语义，`state[28]` dvl_h 在 f297=0.2457、最小值 0.2444@f309、上浮起点 321（f297 在上浮起点之前），机器人仍在最低点、物体抓住但仍贴底 → **v0.2 应改为 true**。BG 同类 key3 修正见 review_report.md §11.1。 |
| 8 | 555 | 297 | NextTo | false | true | both_acceptable | 同 #2 的定义问题。 |
| 9 | 555 | 377 | NextTo | false | true | both_acceptable | 同 #2。 |
| 10 | 556 | 180 | OnSeabed | true | undecidable | both_acceptable | 目标在该帧不可见（红色像素=0，目标 f182 才进入视野）；world state true 可接受但无 ego 证据。 |
| 11 | 556 | 180 | Lifted | false | undecidable | both_acceptable | 同上。 |
| 12 | 556 | 180 | NextTo | false | undecidable | both_acceptable | 同上。 |
| 13 | 556 | 339 | NextTo | false | true | both_acceptable | 定义问题。 |
| 14 | 556 | 419 | NextTo | false | true | both_acceptable | 定义问题（f419 已升离海床，辅助上升始于 ≈360）。 |
| 15 | 1302 | 150 | NextTo | false | true | both_acceptable | 定义问题；且 f150→f168 的"NextTo false→true"视觉差异只是夹爪下降约 5-8 px / 包住圆柱，差异很小（见 `ep001302_f00150/168` 接触表），该动作的可见性本身偏弱。 |
| 16 | 1302 | 196 | NextTo | false | true | both_acceptable | 定义问题。 |
| 17 | 1302 | 415 | NextTo | false | true | both_acceptable | 定义问题；f415 物体仍被夹持（未到 open 命令 448）。 |

**NextTo 结论**：12 个分歧全部是定义/语义问题，不是误标。v0.1 实际语义 = "robot 到达可抓取位置的瞬间"（每 episode 只在
抓取前那一帧 true），但它被翻译成自然语言 "the robot is next to / is no longer next to the red cylinder"，
在抓住后那条动作里产生"the red cylinder becomes grasped … The robot stopped being next to the red cylinder."
的自相矛盾文本。**必须重命名/重定义并改动作模板**（见 review_report.md §6）。

## 2. 可见性分歧裁决（2 格）

| # | episode | frame | 对象 | 原值 | 复核值 | 裁决 | 证据 |
|---:|---|---:|---|---|---|---|---|
| 18 | 555 | 140 | red_cylinder | true | not_visible | **review_ok** | 独立红色像素扫描：f80–f170 红像素面积 = 0（阈值放宽到 R>G+30 仍为 0）；帧内只有右侧一枚蓝圆柱。目标在 f174 才首次进入视野（面积 119 px）。原标注 visibility=true 是**明确错误**。 |
| 19 | 556 | 180 | red_cylinder | true | not_visible | **review_ok** | 同上：f160/f180 红像素 = 0；目标 f182 出现（面积 261 px）。原标注 visibility=true 错误。 |

影响：ep555/f140 与 ep556/f180 分别是 10 题/KI 中的第 1 个 key frame，各被 8/10 道题引用（共 16/70 题）。模型输入的
该帧完全看不到目标，qwen3.8-max 在这些题上仍全对（B 组 40/40），进一步说明文本先验在起作用。

## 3. 关键帧选择/QA 设计问题裁决

| # | 项目 | 裁决 | 证据与建议 |
|---:|---|---|---|
| 20 | 553/f110 为瞬态帧 | review_ok | 该帧是视频中唯一 1 帧的状态（run [110,110]）；前后稳定状态 [88,109] / [112,133]。语义上它只是相机运动中的过渡帧。建议换成 run 稳定帧（112/130）或前一状态代表帧（88）。 |
| 21 | 555/f140、556/f180 目标不可见 | review_ok | 作为"approach"状态代表帧不合格。建议替换为 555: 174–185 或 226–243；556: 182–199 或 238–259（目标可见、仍未抓取）。若保留则必须标 visibility=false 且该帧关系标 unknown，不能进入"已确认可见转移"。 |
| 22 | 1302/f415 是搬运中途、非终态 | review_ok | f415 物体仍被夹持、位于箱子左前方；按钮 1302 的 transfer 终态没有被关键帧覆盖。见 §4。 |
| 23 | 动作文本多子句/自相矛盾 | review_ok（标签语义层） | `compile_action_descriptions` 输出 "…grasped… no longer on the seabed… robot stopped being next to…" 把 3-4 个变化塞进一个动作；3-step 题在跳过中间帧时还会出现 "grasped + lifted + not on seabed + not next to" 的复合动作。建议 v0.2 限制每转移一个主要变化并禁止矛盾子句。 |
| 24 | 视频大量重复帧 | review_ok（数据事实） | 4 条 episode 长度 263/392/429/466 帧，但唯一画面只有 26/35/39/57 个（中位停留 2/12/12/6 帧）。±10~20 帧稳定性检查必须以"唯一状态段"为单位；用像素差判断"动作进行中"不可靠。16 个 key frame 中 15 个落在稳定段，只有 553/f110 是瞬态。 |

## 4. 001302"入箱"专项裁决（Lead 重点）

**结论：没有可确认的入箱证据；不应在 v0.2 把 transfer_inbox / InBox 标成 true。**

证据链：

1. **关键帧层面**：150（海床、未抓）、168（夹爪闭合前包住圆柱）、196（已夹持、未升离）、415（已升离并向箱移动）。
   四个关键帧都没有"物体在箱内"的状态；f415 时绿色箱子在画面右前方、箱口可见，物体仍在夹爪上、位于箱子左侧。
2. **视频尾部**（关键帧 415 之后）：夹爪 open 命令在 **f448** 才发出；f415 时物体仍被夹持，晚 33 帧。释放后到视频结束只有 18 帧。
3. **最后两个唯一画面**（wrist f454、ego f460；其后至 f465 为重复帧）显示：物体仍停留在张开的夹爪之间/箱口近侧边缘上方；
   物体相对两个相机的图像位置几乎不变（ego 红色 bbox 从 442 帧 (93,109,18,18) 到 460 帧 (95,107,18,18)，位移 ≈2 px），
   没有任何一帧显示物体脱离夹爪、落到箱底或低于箱口边缘。wrist 视图（f454–465）在释放后仅出现"夹爪张开、红色面积 468→560 px"的遮挡变化。
4. **辅助信号**：open 命令 f448 后夹爪关节确实由 0.0149 降到 0.0001（f451），但画面里没有可见的释放/沉降结果。
5. 原标注 notes 也写明 "…the object never settles inside the box before the video ends, so Inside/InBox is NOT annotated."
   独立复核同意这一判断，但要注意：**没有任何 key frame 覆盖释放与沉降**，因此"接近箱子"不等于"transfer 完成"。

裁决：`original_ok`（v0.1 未标 InBox 是正确的拒绝）＋ `review_ok`（QA 任务名 "transfer it to the box" 与标签能力不匹配，必须修）。
建议 v0.2：
- 若保留该 episode：新增 `OverBox`/`AboveBoxRim`（可选）+ 显式 `Release` 事件帧，InBox 只在"物体低于箱口/落在箱底"的稳定帧标 true；否则 InBox 留 unknown；
- 或者把 task_text/QA 文本降级为 "Pick up the red cylinder and carry it to the box"（不声称入箱）；
- 或者换一条真正拍到释放+沉降+入箱的 episode 做 transfer 任务。

## 5. 裁决分布汇总

**取值级分歧（19 项）**：

| 裁决 | 数量 | 条目 |
|---|---:|---|
| both_acceptable | 16 | 12 个 NextTo 定义分歧 + 2 个不可见帧 OnSeabed（555/f140、556/f180）+ 2 个不可见帧 Lifted（同上） |
| original_ok | 1 | 555/f297 OnSeabed=false：按 v0.1 模板语义可接受；**按 v0.2 物理支撑语义应改为 true（见 §6）**：世界状态为"抓住但仍贴底"，单帧 320×240 的接触/阴影间隙不可靠 |
| review_ok | 2 | 2 个 visibility 错误（555/f140、556/f180 原标 visible=true，实为 not_visible） |
| undecidable | 0 | — |

**设计/选帧级问题（5 项，均建议修改）**：553/f110 瞬态帧、555/f140 与 556/f180 目标不可见帧、1302/f415 非终态/transfer 无 InBox、
动作文本多子句与矛盾、视频重复帧影响 ±N 帧稳定性判据。

补充：v0.1 的 InGripper 事实 evidence 字段为 `gripper_signal+frame_review`，即抓取标签部分依赖夹爪关节信号（非 ego 图像）——
按 docs/04 §3 的"最低证据"要求，这属于辅助信号，应在 v0.2 中显式记录 `evidence_source` 并把"仅 ego 图可判"与"需辅助信号"分开统计。


## 6. 追加（Lead 补充说明后交叉验证，2026-10-27）

按 Lead 要求用 `observation.state[28]`（dvl_h 离底高度）与 wrist 视频复核 B 组 key3（全部为 close+19/+19/+20/+20 帧）：

| episode | key3 | dvl_h 在 key3 | close 后最小值 | 上浮起点 (10%) | key3 与上浮起点 | v0.1 OnSeabed | v0.2 建议 |
|---|---:|---:|---|---:|---:|---|---|
| 553 | 168 | 0.2284 | 0.2173 @149 | 182 | 早 14 帧 | false | **true** |
| 555 | 297 | 0.2457 | 0.2444 @309 | 321 | 早 24 帧 | false | **true** |
| 556 | 339 | 0.2333 | 0.2333 @338 | 362 | 早 23 帧 | false | **true** |
| 1302 | 196 | 0.2456 | 0.2419 @181 | 227 | 早 31 帧 | false | **true** |

结论：B 组 4 个 key3 的 `OnSeabed=false` 与 A 组 M1–M3 同类，都是"grasped ⇒ 离开海床"的模板推导；按 v0.2 物理支撑语义
应改为 true。该修正把 grasp 转移的动作文本从 "grasped + not on seabed + no longer next to" 变为
"grasped + no longer next to"（仍建议按 §6.3 调整 NextTo 模板）。

事件锚定：B 组 key3 偏移 = +19/+19/+20/+20（规范 +10~20，全部符合）；key2 偏移 = −9/−16/−15/−8
（规范 close−15±5 = [−20,−10]，553 与 1302 偏近 1–2 帧，建议 v0.2 迁移时微调到 −15 附近稳定帧）；
key4 偏移 = +99/+99/+100/+239，对应上浮起点后 +66/+56/+57/+188（555/556 符合 40–60；553 略晚 6 帧，1302 为 transfer 搬运帧）。
7 条 v0.1 annotation 的事实表逐帧完全同构（TFFF/TFFT/FTFF/FTTF），确认模板化标注成立。

1302：dvl_h 在 f415 = 0.7149（接近全程最大 0.7589），说明**已上浮**（相对最低点约 2.96 倍），
但 f415 时仍在箱子左前方、未到箱口；f435 起 dvl_h 降至 0.46（开始向箱口下降），f448 才发 open 命令；
最后唯一画面（wrist f454/ego f460）无释放/沉降/落箱证据 → 1302 **不满足 L=5 transfer_inbox**，
也不满足 release_settle；建议 v0.2 保持 L≤4（pick-up 语义）或改名为 carry-to-box。
