# reviewer_a 独立复核报告（A 组：usim_train_episode_000200 / 000201 / 000552）

复核人：reviewer-a（独立第二方，盲评）
日期：2026-10-27（Asia/Shanghai）
对象：`data/usim_enact/usim-enact-v0.1`（v0.1 原件只读，本复核未修改任何 v0.1 文件）
产物目录：`data/usim_enact/_review/round2/reviewer_a/`

---

## 0. 结论摘要

| 项目 | 结果 |
|---|---|
| 盲评包 | 3 条 episode × 4 关键帧 = 12 帧；relation_scope 4 谓词 → **48 个"帧×关系"判定** |
| Pass 1（盲评） | 先写盘并锁定（`pass1/pass1_lock.json`，含 4 个文件 sha256），锁定后才打开 annotations |
| 帧×关系一致率 | **36/48 = 75.0%**；剔除复核的 4 项 `undecidable` 后 **36/44 = 81.8%** |
| 逐谓词一致率 | `InGripper` **12/12**、`Lifted` **12/12**、`OnSeabed` 8/12（4 undecidable、0 硬分歧）、`NextTo` **4/12** |
| 硬分歧 | **8 处，全部是 NextTo**；Pass 3 裁决：`both_acceptable` 7、`original_ok` 1、`review_ok` 0、`undecidable` 0 |
| 附加可疑点 | 4 项（3 处 key3 `OnSeabed=false` 无物理证据 + 动作文本/模板问题）→ 裁决 `review_ok` 3、`original_ok` 1 |
| 真正必须改值的标签 | **3 处**：ep200 f248 / ep201 f279 / ep552 f284 的 `OnSeabed=false`（建议改 unknown/或按物理定义改 true）；其余是定义、文本、notes、schema 问题 |
| 无法由 ego-only 判定的相邻转移 | **9 个中 7 个**（其余 2 个也只是"距离变化可辨"，阈值仍不可复核） |
| 与 qwen3.8-max 的关系 | 3 处图像条件错误 **全部落在本组 ep200**，且恰好落在 NextTo/抓取阶段与 Lifted 两类最弱环节 → 不能简单归因模型能力 |
| 对 v0.2 的结论 | NextTo 必须显式定义为 approach（取"到达抓取位窗口"，建议 close−15±5 帧事件锚定）；OnSeabed 需物理支撑语义；动作文本必须逐 episode 生成；关键帧应取渲染保持段起点 |

**核心判断：v0.1 的 A 组标签不是"错在某个视觉判断"，而是"错在把模板当成了逐帧证据"。** 7 条 episode 的 4×4 事实表完全相同、动作文本除对象名逐字相同；`manifest` 声称的"21 个相邻转移均可见且非空"可由模板直接推出。真正需要修改的标签值集中在 `OnSeabed`（3 处）和 `NextTo` 的定义/文档（8 处分歧全部是定义问题，见 §6）。

---

## 1. 复核范围、材料与盲评纪律

- **盲评包**：`_review/round2/packets/reviewer_a/`（assignment.json + 3 个 episode JSON；含 episode 身份、任务文本、objects、relation_scope、key_frames 图路径/哈希、qa_usage 图片列表、源视频与 parquet 路径；**不含**逐帧取值、动作文本与参考答案）。
- **盲评纪律**：Pass 1 只使用 `key_frames` 图与 `qa_usage.images`（及同源视频的邻域帧）形成判断；`pass1/` 写盘并记录 sha256（`pass1_lock.json`）之后才读取 `annotations/episodes/*.json`。
- **v0.1 标注文件哈希（复核时）**：
  - `usim_train_episode_000200.json`：`db74fd90af5879f9f72cb084fbcef9445fc41d4e914809013160a4fd0f2c686f`
  - `usim_train_episode_000201.json`：`62bf18b6b769f733b0582df3b8c4c33e24a80db40ac79cacddf0e7e1c15ba0f7`
  - `usim_train_episode_000552.json`：`4d266138fef372a5f3df581c74350745b124cf17de9b08faa7ac343c13a3b897`
- **只读保证**：本复核没有写 v0.1 任何文件；全部产物在 `_review/round2/reviewer_a/` 下。未调用外部 API、未联网。
- **辅助信号使用**：parquet `observation.state[0]`（夹爪，阈值 0.004）与 `state[28]`（DVL 离底高度 `dvl_h`）、`state[27]`（pressure）仅作辅助证据，不单独作标签真值；wrist 视频仅在 Pass 3 用于物理核查，并在报告中标注。

---

## 2. 输入侧审计发现（影响所有题）

1. **QA 图 = raw 帧 + 左上角烧录标签**。96 张 QA 图与对应 raw 帧逐像素比较：差异仅出现在 **y≤29、x≤160** 的标签条带（"Current State / Next State 1/2/3"），条带外像素完全一致；12 个关键帧的主体（夹爪+目标物）都位于 y≥55 区域 → **标签绘制区域不覆盖主体**（证据：`tools_out/qa_labels.png`、`tools_out/label_region_check.png`）。
2. **ego 视频是"渲染保持式"**：`ep200 343 帧只有 42 个唯一画面、ep201 368→35、ep552 374→38`；每个渲染画面被保持约 8–14 帧。**12 个关键帧全部落在保持段内部（不是渲染更新帧）**；"±10~20 帧邻域"通常只有 1–2 个不同画面，不能提供额外时间信息（证据：`tools_out/runs.json`、`tools_out/unique/`）。
3. **12 个关键帧之间两两像素均不同**（非空像素差分成立），但这是"选了不同渲染画面"的结果，不等于语义变化被 ego 可判。
4. **目标物颜色与命名**：蓝圆柱在 ego 流中呈紫色/紫蓝色（v0.1 notes 已说明）；红色目标是肉红色。v0.1 的 notes 把画面中的红色游动物体称作 "red cylinder"，但 wrist 视角显示它是**游动的小鱼**（由远及近再离开、姿态/位置随帧剧变）——notes 事实错误（见 §5）。
5. **场景中确实存在干扰物**：ep552（红圆柱任务）画面中有蓝色条状物（ego 左上/腕部视角下方）；ep200/ep201 另有红色小鱼游动。v0.1 用颜色+形状指代目标基本唯一，但 notes 的指代依据写错了一条。

---

## 3. 逐谓词一致率（A 组）

| 谓词 | 一致 | undecidable（复核放弃） | 硬分歧 | 一致率（不含放弃） | 说明 |
|---|---:|---:|---:|---:|---|
| `OnSeabed` | 8 | 4 | 0 | 8/8 = 100% | 4 项放弃全部在"抓住但可能仍触底"的 key3 帧；Pass3 证明 v0.1 的 false 无物理证据（见 §4/§5） |
| `InGripper` | 12 | 0 | 0 | 12/12 = 100% | close 事件 228/259/264 前后夹爪形态变化明确 |
| `Lifted` | 12 | 0 | 0 | 12/12 = 100% | 值全部正确，但 key4 的 ego-only 可判性弱（上浮仅 ~16 cm） |
| `NextTo` | 4 | 0 | 8 | 4/12 = 33.3% | 8 处分歧全部是定义问题（approach vs 几何距离），非视觉判断分歧 |
| **合计** | **36** | **4** | **8** | **36/44 = 81.8%** | 精确一致率 36/48 = 75.0% |

分 episode：ep200 11 一致 / 1 放弃 / 4 分歧；ep201 13 / 1 / 2；ep552 12 / 2 / 2（每 episode 16 项）。

**重要提醒**：`InGripper`/`Lifted` 的 12/12 一致**不能**当作"标签已被独立验证"——它们与"抓取生命周期模板"一致，样本本身恰好落在模板成立的位置；真正的风险在模板与逐帧证据不一致的地方（key3 OnSeabed、key4 Lifted 的 ego 可见性）。

---

## 4. 必须修改的标签清单

| # | episode | frame | 关系 | 原值 | 建议值 | 理由 | 证据 |
|---|---|---|---|---|---|---|---|
| M1 | usim_train_episode_000200 | 248 | `OnSeabed` | false | **unknown（v0.2 三值）或按物理定义 true** | 无任何离底证据：dvl_h=0.2353（本 episode 最低点），上浮起点 f271；wrist 显示夹紧后物体相对夹爪无竖直位移；物体在 f161 已进入夹爪口部但一直处于底部高度 | `pass3/context/wrist_ctx_200_248.png`、`pass3/unique`、`pass3/signals.json` |
| M2 | usim_train_episode_000201 | 279 | `OnSeabed` | false | 同上 | dvl_h=0.2313 最低点、上浮起点 f301；相对 key2(f244, 0.2848) 还下降 5 cm；无离底证据 | `pass3/context/wrist_ctx_201_279.png`、`pass3/signals.json` |
| M3 | usim_train_episode_000552 | 284 | `OnSeabed` | false | 同上 | dvl_h=0.2597 最低点、上浮起点 f306；wrist close(264) 后无竖直提升 | `pass3/context/wrist_ctx_552_284.png`、`pass3/signals.json` |
| M4 | ep200 + ep201 | notes | 对象说明 | "a red cylinder is also present / visible" | **"a red fish is visible"** | 红色物体是游动小鱼（wrist 视角由远及近再离开、姿态剧变），不是圆柱 | `tools_out/redobj_ep200.png`、`tools_out/redobj_ep201.png`、`pass3/wrist_unique/` |
| M5 | 全部 7 条 episode（跨组） | — | 标注方式 | 模板事实表 | **v0.2 逐帧独立标注** | 7 条 episode 的 4×4 事实表完全相同、动作文本除对象名逐字相同 → 不是逐帧判读；"21 个相邻转移均非空"是模板推论 | `pass2_disagreements.json` → `special_audits.annotation_template` |

**NextTo 的 8 处分歧不列入"必须改值"，而列入"必须改定义/文档/文本"**（Lead 已裁决为语义定义问题）：

| # | 范围 | 问题 | 要求 |
|---|---|---|---|
| N1 | 全 v0.1/v0.2 | `NextTo` 名字像几何关系，实际是 approach 阶段 | 文档显式写明：approach（末端进入抓取位窗口、尚未夹紧；抓住后恒 false；**不是纯几何距离**） |
| N2 | 全 v0.1/v0.2 | 动作文本 transition 2 输出 "grasped + no longer next to"（自然语义矛盾） | 文本生成器禁止该句式；改为"机器人闭爪夹住仍贴在海床上的物体"一类可证描述 |
| N3 | ep200 f140 | approach 窗口边界未写，f140 是否 true 取决于边界定义（wrist 显示尚有 10–15 px 空隙、到达≈f161） | v0.2 用事件锚定（close−15±5 帧内且 InGripper=false、OnSeabed=true 的稳定帧），并在 notes 记录 |
| N4 | ep552 f120 | 在 approach 两种读法下都应为 false（wrist 相距 ~40–50 px、到 close 还有 144 帧） | 无需改值；保留为 key1 |

---

## 5. 无法由 ego-only 判定的转移清单（本组 9 个相邻转移）

| # | episode | 转移 | v0.1 净变化（模板） | 仅凭 ego 可判？ | 原因 |
|---|---|---|---|---|---|
| T1 | 200 | 140→213 | NextTo F→T | **否（partial）** | 变化本质是"是否已到达抓取位"的距离/阶段阈值；ego 视角被深度压缩，f140 甚至看起来已接触；真正可判的是"物体被拨倒" |
| T2 | 200 | 213→248 | OnSeabed T→F、InGripper F→T、NextTo T→F | **否（partial）** | 张/合爪差异小；`OnSeabed` 物理上未翻转（见 M1）；`NextTo` 依赖定义 |
| T3 | 200 | 248→328 | Lifted F→T | **否（partial）** | 上浮仅 ~16 cm，ego 单帧无清晰离底间隙；需跨帧/辅助信号 |
| T4 | 201 | 199→244 | NextTo F→T | 部分可判（→近距离变化明显） | 距离变化在 ego 上明显，但"何时算 next to"的阈值仍不可复核 |
| T5 | 201 | 244→279 | OnSeabed T→F、InGripper F→T、NextTo T→F | **否（partial）** | 同 T2；`OnSeabed` 无物理证据（M2） |
| T6 | 201 | 279→357 | Lifted F→T | **否（partial）** | 同 T3 |
| T7 | 552 | 120→249 | NextTo F→T | 部分可判 | 夹爪下降到物体上可辨；阈值不可复核 |
| T8 | 552 | 249→284 | OnSeabed T→F、InGripper F→T、NextTo T→F | **否（partial）** | 同 T2；`OnSeabed` 无物理证据（M3） |
| T9 | 552 | 284→364 | Lifted F→T | **否（partial）** | 同 T3 |

**结论：9 个相邻转移中没有一个是"仅凭 ego 且定义完备下可复核"的干净转移。** 7 个依赖 `NextTo` 阶段定义或 ~16 cm 的 `Lifted` 上浮；剩下 2 个（T4/T7）虽有可见距离变化，但缺阈值定义，严格来说也不可复核。这与 `docs/06 §4` 的"每个转移非空且可见"验收要求冲突：**非空 ≠ ego 可判**。

---

## 6. NextTo 定义建议（结合 Lead 裁决与 v0.2 规范）

1. **采用 approach 语义并在规范中显式写明**（v0.2 规范 §2.2 已写入，建议补窗口边界）：
   `NextTo(robot,obj)` = 机器人末端进入"抓取位姿窗口"、尚未夹紧的接近阶段；**抓住后恒 false；不是纯几何距离**。
2. **窗口边界建议事件锚定（可复核）**：`NextTo=true` 只取夹爪 close 事件前 **15±5 帧**、且 `InGripper=false`、`OnSeabed=true` 的稳定帧。本组 3 条 episode 的 key2 **全部精确等于 close−15**（213 vs 228、244 vs 259、249 vs 264），key1 = close−88/−60/−144、key3 = close+20，因此 v0.1 的 `F→T→F→F` 在该定义下**完全自洽**（Pass 3 §4 给完整证据链）。
3. **ep200 f140 是唯一边界帧**：wrist 显示 f140 时夹爪与物体仍有 10–15 px 可见空隙、真正"到达"约在 f161，因此"到达窗口"定义下 false 自洽；若采用"末端已靠近且未抓住"的宽口径 approach 则应为 true。**v0.1 没写边界，所以不可复核；v0.2 必须写。**
4. **ep552 f120 无需改值**：wrist 相距 ~40–50 px、到 close 还有 144 帧，两种读法下都是 false。
5. **动作文本**：NextTo 采用 approach 语义后，transition 2 不能生成 "grasped + no longer next to" 这种矛盾句；建议同时写"仍贴海床"或"闭爪夹住"的可证描述。
6. **`Touching`（v0.2 若启用）**必须同样事件锚定（close 前、物体仍在海床、ego 可见接触），否则会与 `NextTo` 混淆（两者都在 close 前窗口）。

---

## 7. 关键帧选择问题

1. **12 个关键帧全部落在渲染保持段内部（不是"新画面"的第一帧）**：`offset` = 2（f140）、3（f213）、16（f248）、22（f328）等。语义上可接受（画面稳定 ≥12 帧），但 QA 图是"保持画面"的拷贝，且 **±10~20 帧邻域几乎无新信息**。
2. **v0.1 key 选择规则不透明**：4 个关键帧与 close 事件严格同构（key2=close−15、key3=close+20），看起来是"按事件等距取样"而非"按语义状态变化取样"。这导致 key1→key2 的变化可能只是"距离阈值"而非语义事件。
3. **key3 帧选择落在"夹住但仍贴海床"的时刻**，而该时刻在 ego 上 **无法判定 `OnSeabed`**（这次复核 4 个 undecidable 全部出现在这种帧）。若改用"离底且可见间隙 ≥ 物体半宽"的帧作为 grasp/lift 之间的状态，`OnSeabed=false` 才有可证像素证据。
4. **建议 v0.2 选帧规则**（可直接写入规范）：
   - 只在**渲染保持段的第一帧**（`run start`）或段内任选但记录 run 区间；相邻关键帧至少相隔 **2 个渲染更新**（≥20–25 帧）以保证画面差分；
   - key2（approach）用事件锚定（close−15±5，且 InGripper=false、OnSeabed=true）；
   - key3（grasp）取 close+10~20 且 `OnSeabed` 可辨的稳定帧（若仍贴底则按物理定义 `OnSeabed=true`）；
   - key4（lift）取上浮起点之后、ego 可见离底间隙的稳定帧（本组上浮 ~16 cm，约在 ascent onset 之后 40–60 帧）；
   - 每帧记录 `hold_run`（画面保持区间）与"画面是否静止 ≥10 帧"证据。
5. **帧号/时间戳/模型输出不能参与选帧**（v0.2 规范 §3.5 已写）；本次复核发现 v0.1 的等距模式与 close 事件严格相关，存在"用信号事件选帧"的嫌疑，建议在 v0.2 报告中说明。

---

## 8. 对 v0.2 标注指南的具体建议

1. **谓词定义（最高优先级）**
   - `NextTo`：显式 approach 语义 + 事件锚定窗口（见 §6）；笔记必须写明"本 episode 采用 approach 定义"。
   - `OnSeabed`：改为**物理支撑语义**（物体被海床支撑、未被夹持或悬空；被夹住且仍贴底时仍为 true），避免"grasped ⇒ 自动 false"的模板推导；若仍要生命周期语义，应在文档里把 `OnSeabed` 改名为 `Stage_OnSeabed` 并声明互斥。
   - `Lifted`：按 v0.2 规范"可见间隙 ≥ 物体半宽"执行；`dvl_h/pressure` 只作辅助并写入 notes，不作唯一证据。
   - 三值 unknown 只用于标注过程中的工作副本；进 scope 的谓词必须在全部关键帧可判（v0.2 §2.3 已写）。
2. **动作文本生成**
   - 禁止用"模板+差分"生成固定生命周期文本；每个 transition 的动作文本必须由该 episode 的已验证事实产生，并可由人工复核；
   - 禁止出现"抓住 + 不再在旁边"的矛盾句（本次 8 处 NextTo 分歧全部来自模板语义）；
   - 建议同时保存"文本来源版本"，避免仅凭文本先验答题（条件 C 已显示 inverse EM 0.93–1.00）。
3. **关键帧与状态数**
   - 优先 L=4/5，避免 L=3（占 56/70、机会 EM 0.5 无分辨力）；
   - L=5 路线按优先级 transfer_inbox > release_settle > touching；找不到 5 个可辨状态就标 4 帧并在 notes 说明（v0.2 规范已写）。
4. **独立复核流程**
   - 每条 episode 至少 2 位独立标注者 + 1 位裁决者；第一次标注必须先写盘锁哈希再对照（本次流程可复用 `pass1_lock.json` 机制）；
   - 复核必须记录"ego 可判性"字段（yes/partial/no），与"事实值"分开；本次 4 个 `OnSeabed` undecidable 就是 ego 不可判的直接证据；
   - wrist/夹爪信号的使用必须在 notes 中逐条记录用途，且不能让辅助信号单独决定标签。
5. **输入与元数据**
   - QA 图可继续烧录 "Current State / Next State N"（本组已验证不遮主体），但建议把标签区域坐标写进 manifest，方便第三方核对；
   - 记录视频渲染保持结构（唯一画面时间线）与关键帧所在 run，供复核定位；
   - 记录 close/open 事件帧、dvl_h 摘要作为**辅助元数据**（不当作标签真值）。
6. **报告口径**
   - 保留**去图条件 C** 与文本基线（已证实 inverse 基本由文本先验决定）；
   - 按 episode 聚类做配对比较（70/28/21 题来自少数轨迹，不能当独立样本）；
   - 评估前先做标签 gate：标签争议、ego 不可判、模板化事实表必须单列，不能只删模型答错的题。
7. **指代与干扰物**
   - 每个 episode 只标 1 个被操作目标；notes 必须写明指代依据（颜色/位置）并**核对**干扰物描述（本次"red cylinder"实为 fish）；
   - 蓝圆柱在 ego 中呈紫色，建议 description 保留"blue cylinder (purple appearance in ego)"。
8. **与 v0.1 的关系**
   - v0.1 的 21 个相邻转移"均非空"是模板推论；若在 v0.2 报告中引用，应注明这是 schema 层非空，**不等于 ego 可见**。
   - 本报告的 M1–M3 与 N1–N4 应在 v0.2 规范/报告中列为"与 v0.1 的已知差异"。

---

## 9. 与 qwen3.8-max 执行结果（70 题 EM 0.9571 / 去图 0.7286）的关系

复核时重新比对了 `runs/qwen3.8-max/dev_ego_thinking_false_001/full_v1/predictions.jsonl` 与 QA，确认 **3 处图像条件错误全部在 usim_train_episode_000200（本组）**：

| 错误 | 题 | gt → ans | 对应本复核的薄弱环节 |
|---|---|---|---|
| 1 | ep200 forward L=4（140,213,248,328） | [1,3,2] → [3,1,2] | 把 248（已夹住）与 213（approach 帧）顺序对调 → 正是 T1/T2 的 NextTo/抓取阶段语义 + ego 不可判点 |
| 2 | ep200 forward L=3（140,213,248） | [2,1] → [1,2] | 同上（248 与 213 对调） |
| 3 | ep200 inverse L=3（213,248,328） | [2,1] → [1,2] | 把 "lifted" 映射到 213→248、把 "grasped" 映射到 248→328 → 正是 T2/T3 的 OnSeabed/Lifted ego 可见性弱点 |

- 条件 C（去图）同 3 题也错；inverse L=3 去图 EM 0.9286、L=4 1.0000 → 文本先验已接近满分。
- **结论：0.9571 的残差集中在标签/可见性最弱的转移上，不能直接读成模型能力缺口。** v0.2 应先修定义（NextTo/OnSeabed）、提高 ego 可见性（key4 选在可见离底间隙处），再评估模型；否则 L=4 的少量错误无法区分"模型错"与"标签不可判"。

---

## 10. 风险与未决问题

1. **A 组之外的 4 条 episode（B 组）未由我复核**：我已用 `compile_action_descriptions` 确认 **7 条 episode 的事实表与动作文本完全同构**（模板），因此 B 组大概率存在同类的 `OnSeabed`/`NextTo` 问题；建议 Lead 让 reviewer_b 交叉验证同一 `special_audits.annotation_template`。
2. **Pass 1 的 ego-only 判断有 1 处误判**（ep552 f120 NextTo：ego 深度压缩造成"已在旁边"的错觉；wrist 证明物体相距 ~40–50 px）。这恰好说明 **ego-only 标注对距离/接触不可靠**，v0.2 若坚持 ego-only 主结果，必须给阈值/事件锚定，否则同类误判会进入标签。
3. **`Lifted` 的物理证据依赖辅助信号 `dvl_h`**（ego 单帧弱）。本组 key4 的 true 值正确，但"可否由 ego 图像判定"仅 partial；v0.2 需把 key4 选在可见离底间隙处，否则 L=4/5 的最后一个转移仍不可复核。
4. **`OnSeabed` 三处建议值 unknown**：若 v0.2 按"物理支撑"语义并仍以这些帧为 key3，应改 key3 为 `OnSeabed=true`（物体贴底被夹住）或在 notes 里记录"夹持中仍贴底"；这会改变 v0.1 的"中间状态"叙事，需在 v0.2 规范里说明。
5. **动作文本模板导致的文本先验**：v0.2 若仍生成"生命周期排序"文本，inverse 题仍会被文本先验解出；建议 inverse 主结果附带文本基线，并考虑更难的多答案/多对象变体。
6. **渲染保持结构**：±10~20 帧邻域信息量极低；若 v0.2 仍按"±20 帧"做稳定性检查，会得到"全部稳定"的假象。建议以唯一画面时间线为准。
7. **未决问题（需 Lead 决定）**：v0.1 的 A 组标签是否需要按本报告 M1–M3 做 patch（如 v0.1.1）并重跑全部模型；还是只在 v0.2 中修正。本报告不修改 v0.1 原件。

---

## 11. 产物清单与复现

| 产物 | 说明 |
|---|---|
| `pass1/usim_train_episode_0002{00,01}.json`、`pass1/usim_train_episode_000552.json` | Pass 1 盲评：12 帧 × （4 关系 + 2 对象可见性 + 稳定性 + ego 可判性），含像素证据 |
| `pass1/summary.json` | 盲评汇总（48 项：true 25 / false 19 / undecidable 4；ego-only yes 20 / partial 24 / no 4） |
| `pass1/pass1_lock.json` | 盲评写盘时间与 sha256（4 文件）——盲评纪律证据 |
| `pass2_disagreements.json` | 逐帧对照 48 项（agree 36 / abstain 4 / disagree 8）、逐谓词统计、9 个相邻转移检查、动作文本复核、特殊审计 |
| `pass3/adjudication.json` | 19 项裁决（8 分歧 + 4 中止项 + 7 可疑点），含 NextTo approach 语义自洽性证据链 |
| `pass3_adjudication.md` | 裁决表与三条核心结论 |
| `review_report.md` | 本报告 |
| `pass3/context/ego_ctx_*.png`、`pass3/context/wrist_ctx_*.png` | 关键帧 ±15/±30/±60 帧 ego/wrist 接触表（12 帧 × 2 视角） |
| `pass3/signals.json` | 夹爪 close 事件、dvl_h/pressure、上浮起点、每关键帧辅助信号值（辅助证据，非真值） |
| `pass3/wrist_unique/`、`tools_out/unique/` | ego/wrist 全片"唯一画面"时间线接触表（复核定位用） |
| `tools/gen_pass1.py`、`tools/gen_pass2.py`、`tools/review_sheets.py` | 可复现脚本（输出均写 reviewer_a 目录） |

复现命令（在 `ENACT/` 下）：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
& $py data\usim_enact\_review\round2\reviewer_a\tools\gen_pass1.py
& $py data\usim_enact\_review\round2\reviewer_a\tools\gen_pass2.py
# Pass 3 证据表由 annotate_helper/review_sheets.py 生成，见 tools/ 与 pass3/context/
```
