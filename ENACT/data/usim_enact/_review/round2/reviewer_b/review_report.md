# ENACT × USIM v0.1 标签独立复核报告（reviewer_b / B 组）

复核人：reviewer_b（独立第二方）
日期：2026-10-27（Asia/Shanghai）
对象：`usim-enact-v0.1` 的 B 组 4 条 train episode（553、555、556、1302），16 个关键帧、12 个相邻转移。
流程：**Pass 1 盲评先写盘**（写盘前未打开任何 `annotations/` 文件）→ Pass 2 对照标签与 `compile_action_descriptions`
→ Pass 3 视频上下文 + 夹爪/深度辅助信号裁决。任务 id：`task-2`。

## 0. 结论摘要

1. **B 组 40/70 道题全部被模型答对（40/40 EM）**；qwen3.8-max 全 70 题中的 3 处错误全部在 **ep000200（A 组）**，
   不在本组。因此本组标签问题没有被"模型答错"暴露，但也不代表标签经得起 ego-only 复核。
2. **关系标签逐格一致率 73.4%（47/64）**，剔除复核侧 7 个"不可判定"后为 **82.5%（47/57）**。
   按谓词：`InGripper` 16/16（100%）、`Lifted` 14/16（87.5%）、`OnSeabed` 13/16（81.3%）、
   `NextTo` 4/16（25%）。
3. **NextTo 的 12 个分歧全部是定义问题**：v0.1 实际语义是"robot 到达抓取位的瞬间"，但动作文本被翻译成
   "the robot is (no longer) next to the red cylinder"，在抓取动作里产生自相矛盾子句（"变成被抓取 + 不再在物体旁边"）。
   这是最需要版本化修复的标签语义问题。
4. **2 处 visibility 明确错误**：ep555/f140、ep556/f180 的目标红圆柱在该帧**完全不可见**（红色像素=0），
   但标签写 `visibility=true`；这两帧还是各 episode 的第一个关键帧，被 16/70 道题引用。
5. **中间态可辨性不足**：553/f168、555/f297、556/f339、1302/f196 的 "OnSeabed=false + InGripper=true + Lifted=false"
   物理上成立（夹爪信号 + 深度辅助信号都支持），但 320×240 ego 单帧只有 2–4 px 的间隙/阴影差异，**不能作为 ego-only 确定证据**。
   标签的 `InGripper` evidence 本身就写了 `gripper_signal+frame_review`（依赖辅助信号）。
6. **1302 没有可确认的入箱证据**（详见 §5）：关键帧只到"已升离、向箱移动"；释放命令 f448 后到结束仅 18 帧，
   最后唯一画面仍显示物体停在张开的夹爪之间/箱口近侧，没有任何一帧显示物体脱离、沉降、落于箱底。
   v0.1 不标 InBox 是正确的，但 QA 题面写 "transfer it to the box" 属于任务名与标签能力不匹配。
7. **关键帧选择问题**：16 帧中 15 帧落在稳定段，但 553/f110 是视频中仅 1 帧的瞬态；555/f140 与 556/f180 目标不可见；
   1302/f415 是搬运中途而非终态。另有数据事实：4 条 episode 虽有 263/392/429/466 帧，但只有 26/35/39/57 个唯一画面
   （大量重复帧），±10~20 帧"稳定性"必须以唯一状态段而不是像素差来判定。
8. **交叉验证 reviewer-a / Lead 的 v0.2 裁决（B 组）**：B 组同样支持"OnSeabed 物理支撑语义"修正——
   **553/f168、555/f297、556/f339、1302/f196 四个 key3 帧的 `OnSeabed=false` 无物理证据**：
   4 条 episode 的 `state[28]`（dvl 离底高度）最小值均在 close 帧附近（f149/309/338/181），
   上浮起点在 **key3 之后 23–35 帧**（182/321/362/227），即 key3 时机器人仍在最低点、物体被夹住但仍贴底，
   按 v0.2 定义应改为 `OnSeabed=true`（与 A 组 M1–M3 结论一致）。详见 §11。
9. **模板同构性确认**：7 条 v0.1 annotation 的事实表逐帧完全同构（`TFFF/TFFT/FTFF/FTTF` × OnSeabed/InGripper/Lifted/NextTo），
   与目标颜色、场景批次、任务均无关，确属模板产物（reviewer-a 的观察成立）。

## 1. 复核方法（可复现）

| Pass | 输入 | 产物 |
|---|---|---|
| Pass 1（盲评） | 盲评包 `packets/reviewer_b/`（身份/任务/objects/relation_scope/key_frames/qa_usage/source_media），关键帧 raw 图 + 模型实际收到的 QA 图，关键帧 ±20 帧（仅用于稳定性判断） | `pass1/usim_train_episode_*.json`、`pass1/summary.json`、`pass1/sha256.json`（写盘后记录哈希，之后才读 annotations） |
| Pass 2（对照） | `annotations/episodes/*.json`、`enact.adapters.usim_annotations.compile_action_descriptions`、QA 文本（只读校验） | `pass2_disagreements.json` |
| Pass 3（裁决） | ego 视频 ±15/30/60 帧接触表（每格标注帧/夹爪/压力）、wrist 视频、parquet `observation.state[0]`（夹爪）与 `state[27]`（深度代理，仅辅助） | `pass3_adjudication.md`、`pass3/*.png`、`pass3/aux_lift_signal.json` |

复核包与基础设施核验：
- 16 个关键帧 raw PNG 的 SHA-256 **全部与盲评包一致**；segmented 图与 raw 图逐字节相同（本组 segmented = raw）。
- 32 张/集 QA 图逐张与 raw 图做**掩码像素比对**：除左上角烧录的 `Current State` / `Next State N` 标签区外，像素差为 0，
  即模型看到的确实是关键帧原图（标签文字只透露"当前/未来第 N 张"的角色，不透露语义）。
- forward 题的展示顺序与 chronological 顺序不同（future 图被打乱）；inverse 题为时间顺序。逐槽位到源帧的映射见
  `work/qa_slot_frame_map.json`。
- pass1 文件哈希：`summary.json=5d0666cd…`、`…000553.json=8c0062c5…`、`…000555.json=e571802d…`、
  `…000556.json=58be209a…`、`…001302.json=90a0d43e…`（完整值见 `pass1/sha256.json`）。

## 2. 逐谓词一致率（B 组 16 帧 × 4 关系 = 64 格）

| 谓词 | 一致 | 总格数 | 一致率 | 说明 |
|---|---:|---:|---:|---|
| `InGripper(red_cylinder)` | 16 | 16 | 100.0% | 抓取/未抓取的可见判定全部一致 |
| `Lifted(red_cylinder)` | 14 | 16 | 87.5% | 2 个分歧均为"目标不可见帧"（555/f140、556/f180）上的复核侧 undecidable |
| `OnSeabed(red_cylinder)` | 13 | 16 | 81.3% | 3 个分歧：2 个不可见帧 + 555/f297 中间态边界 |
| `NextTo(robot, red_cylinder)` | 4 | 16 | 25.0% | 12 个分歧全部为定义/语义问题，不是随机误标 |
| **合计（关系格）** | **47** | **64** | **73.4%** | 剔除复核侧 7 个 undecidable 后 47/57 = **82.5%** |
| 可见性（robot + red_cylinder） | 30 | 32 | 93.8% | 2 个分歧=两处 visibility 错误（555/f140、556/f180） |

12 个相邻转移：`compile_action_descriptions` 结果**全部非空**（12/12 有可见 diff），没有空签名转移；
但其中 8/12 的动作文本包含 3–4 个子句（一个转移里同时改变 OnSeabed/InGripper/NextTo 甚至 Lifted），
文本可排序性极强——这与执行结果文档中"去图 EMA 0.7286"的文本先验一致。

## 3. 12 个转移的 ego-only 可判性清单

| # | episode | 转移 | 动作文本（v0.1 编译） | ego-only 可判性 |
|---:|---|---|---|---|
| 1 | 553 | 110→140 | robot becomes next to the cylinder | **弱**：两帧夹爪都接近物体，差异只是"再下降几像素"；单帧难定量 |
| 2 | 553 | 140→168 | grasped + not on seabed + robot no longer next to | **部分**：grasp 可见；"离开海床"是 2–4 px 阴影间隙，单帧不可靠 |
| 3 | 553 | 168→248 | lifted above the seabed | **需两帧对比/视频**：阴影与水柱变化可判，单帧无度量 |
| 4 | 555 | 140→262 | robot becomes next to the cylinder | **不可**：from 帧目标不可见（red px=0），且 visibility 标错 |
| 5 | 555 | 262→297 | grasped + not on seabed + no longer next to | **部分**：grasp 可见；OnSeabed 边界不可靠 |
| 6 | 555 | 297→377 | lifted above the seabed | **需两帧对比/视频** |
| 7 | 556 | 180→304 | robot becomes next to the cylinder | **不可**：from 帧目标不可见 |
| 8 | 556 | 304→339 | grasped + not on seabed + no longer next to | **部分**：grasp 可见；OnSeabed 边界不可靠 |
| 9 | 556 | 339→419 | lifted above the seabed | **需两帧对比/视频** |
| 10 | 1302 | 150→168 | robot becomes next to the cylinder | **弱**：差异只是夹爪下降约 5–8 px 并包住圆柱 |
| 11 | 1302 | 168→196 | grasped + not on seabed + no longer next to | **部分**：grasp 可见；OnSeabed/边界不可靠（且 InGripper 依赖夹爪信号） |
| 12 | 1302 | 196→415 | lifted above the seabed | **需两帧对比/视频**；且这是"transfer"任务的最后一步，却没有任何箱内状态 |

结论：**没有任何一个转移能在"两张静态关键帧、仅 ego、无辅助信号"的严格条件下被 100% 确证**；
其中 **#4、#7 完全不可判**（from 帧目标不可见），#2/#5/#8/#11 的"离开海床"子句是**边缘可辨**，
#3/#6/#9/#12 的"升离"只能通过前后帧对比或深度信号辅助判断。v0.2 需要为每个 changed relation 增加
`ego_only_visible` 标记，并把"仅 ego 图可判"与"需辅助信号"分表统计。

## 4. 必须修改的标签清单（v0.2 必须处理）

| # | episode | frame | 关系/字段 | 原值 | 建议值 | 理由 |
|---:|---|---:|---|---|---|---|
| 1 | 555 | 140 | `visibility.red_cylinder` | true | **false** | 红像素面积=0，目标完全不在画面内（f174 才进入视野） |
| 2 | 556 | 180 | `visibility.red_cylinder` | true | **false** | 红像素面积=0，目标 f182 才进入视野 |
| 3 | 555 | 140 | OnSeabed / Lifted / NextTo | true / false / false | **unknown（或该帧退出 QA）** | 目标不可见，事实无 ego 证据；world state 可由视频连续性接受，但不能作为"可见转移"端点 |
| 4 | 556 | 180 | OnSeabed / Lifted / NextTo | true / false / false | **unknown（或该帧退出 QA）** | 同上 |
| 5 | 全部 4 条 | 抓取后各帧 | `NextTo(robot,cylinder)` | false | **保留 false 但重命名/重定义** | 语义="抓取前到位瞬间"；动作文本 "no longer next to" 自相矛盾（详见 §6） |
| 6 | 553 | 110 | key frame 选择 | （标签值本身可接受） | **换为 112–133 或 88–109 的稳定帧** | f110 是视频中唯一 1 帧的瞬态状态，不代表稳定语义状态 |
| 7 | 555 | 140 | key frame 选择 | — | **换为 174–185 或 226–243** | 目标不可见，作为 approach 状态代表帧不合格 |
| 8 | 556 | 180 | key frame 选择 | — | **换为 182–199 或 238–259** | 同上 |
| 9 | 1302 | 415 附近 | 转移/任务范围 | 4 帧止于"已升离、向箱移动" | **补释放+沉降终态帧，或把任务降级为 carry-to-box；不要声称 transfer 成功** | 见 §5：没有可确认入箱证据 |
| 10 | 553 | 168 | `OnSeabed` | false | **true（v0.2 物理支撑语义）** | key3 帧，dvl_h=0.2284，最小值 0.2173@f149，上浮起点 182；抓住但仍贴底 |
| 11 | 555 | 297 | `OnSeabed` | false | **true（v0.2 物理支撑语义）** | key3 帧，dvl_h=0.2457，最小值 0.2444@f309，上浮起点 321 |
| 12 | 556 | 339 | `OnSeabed` | false | **true（v0.2 物理支撑语义）** | key3 帧，dvl_h=0.2333 = 全局最小（@f338），上浮起点 362 |
| 13 | 1302 | 196 | `OnSeabed` | false | **true（v0.2 物理支撑语义）** | key3 帧，dvl_h=0.2456，最小值 0.2419@f181，上浮起点 227 |

说明：#10–#13 是 reviewer-a 在 A 组发现的 M1–M3 同类问题在 B 组的复现；若 v0.2 迁移 v0.1 的 7 条数据，
必须同时修正 B 组这 4 帧（否则 7 条迁移数据仍带模板推导错误）。届时 B 组的 4 个 grasp 转移将变成
"grasped（InGripper F→T）"+"robot 离开 approach 位（NextTo T→F）"两个子句，不再包含 OnSeabed 变化。


补充（非必须但建议）：
- `InGripper` 的 evidence 为 `gripper_signal+frame_review`，依赖夹爪关节信号；v0.2 应增加 `evidence_source` 字段
  （`ego_visual` / `aux_signal` / `motion_consistency`），并禁止把纯辅助信号结论当作 ego-only 标签。
- v0.1 的 visibility 是布尔值；f110（物体下缘被裁切）这类"部分可见"应允许 `partial` 或记录 bbox/像素计数。

## 5. 001302 "入箱"结论（重点）

**没有可确认的入箱/释放证据；不能支持 transfer 语义，也不能标 InBox=true。**

证据：
1. 关键帧四态：150（海床、未抓）→168（夹爪闭合前包住圆柱）→196（已夹持、未升离）→415（已升离、向箱移动）。
   f150/168/196 画面里绿箱在背景中可见；f415 时箱子在右前方、箱口朝向相机，**物体仍在夹爪上、位于箱子左侧**。
2. 释放命令在 **f448**（`observation.state[0]` 于 f448 后由 0.0149 降到 0.0001），f415 时仍闭合；释放后到视频结束（f465）只有 18 帧。
3. 视频最后两个唯一画面（wrist f454、ego f460；此后至 f465 为重复帧）显示物体仍停在张开的夹爪之间/箱口近侧边缘上方；
   物体相对相机的图像位置几乎不动（ego 红 bbox (93,109,18,18)→(95,107,18,18)，≈2 px），没有任何一帧显示物体脱离夹爪、
   低于箱口或落到箱底；wrist 视图释放后只出现"夹爪张开、红色面积 468→560 px"的遮挡变化。
4. v0.1 标注 notes 也明确说 "…the object never settles inside the box before the video ends, so Inside/InBox is NOT annotated."
   —— 独立复核**同意不做 InBox 断言**，但指出：**key frame 集合完全没有覆盖释放与沉降**，因此"接近箱子"不能当作 transfer。
5. 该集 QA 的 10 道题的动作文本**从不出现 box/transfer 字样**（已 grep 全部 B 组题面）；模型实际只回答
   "approach → grasp → lift" 三步的排序。也就是说：任务名叫 transfer，题面测的却只是 pick-up。

建议（三选一，按优先级）：
- **A（推荐）**：v0.2 若保留该集，新增 `AboveBoxRim`（物体在箱口上方、稳定 N 帧）作为可复核中间谓词，
  并只在"释放后物体低于箱口/落于箱底且稳定 ≥N 帧"时标 `InBox=true`；否则 `InBox=unknown`，QA 题面改为
  "carry the red cylinder to the box"；
- **B**：另采/另选一条真正拍到释放→沉降→入箱的 episode 做 transfer 任务；
- **C**：从 v0.2 题集中移除 1302，避免"transfer"名不副实。

## 6. NextTo 定义建议

问题：v0.1 的 `NextTo` 只在"抓取前到位"那一帧为 true（4 条 episode 都是 pattern：approach 帧 false → 抓取前帧 true
→ 抓取后所有帧 false），但 `USIMStateChangeTranslator` 把它翻译成自然语言 "next to / no longer next to"，
于是抓取转移的动作变成：

> "The red cylinder becomes grasped by the robot. The red cylinder is not on the seabed anymore. **The robot is no longer next to the red cylinder.**"

这在物理上自相矛盾（机器人正抓着物体，却说不在物体旁边），也会给文本先验提供额外的"时间标记"。

建议（与 Lead 的 v0.2 规范方向一致）：
1. **显式定义**：`NextTo(robot, obj)` = "robot 末端执行器已到达抓取前位姿（approach complete，尚未闭合夹爪）"；
   抓住/释放后恒 false。文档中写清，不再按自然语言"邻近"理解。
2. **重命名**（更彻底）：`ApproachReady(robot, obj)` 或 `AtGraspPose(robot, obj)`，把谓词名和语义绑定；
   若保留 `NextTo` 名字，必须在 annotation schema 里写 `definition_version`。
3. **改动作模板**：`remove NextTo` 不要译成 "no longer next to"，改为
   "the robot has finished the approach / leaves the pre-grasp pose"；或按"一个转移一个主变化"原则，
   grasp 转移只保留 grasp（+必要的 on-seabed），NextTo 只作为状态记录、不进动作文本。
4. **可选**：若未来能拿到位姿/距离真值，改成距离阈值 `Near(robot,obj, d≤d0)`，抓住后仍为 true，
   从根上消除自相矛盾。
5. 对比基线：任何 v0.2 题集在文本里若仍出现 "next to / no longer next to"，需要在复算文本先验（去图条件）
   后确认没有人为可排序的正负面标记不对齐。

## 7. 关键帧选择问题（数据层面）

1. **视频大量重复帧**：ep553/555/556/1302 解码长度 263/392/429/466，唯一画面只有 26/35/39/57；同一状态最多停留 26–30 帧。
   16 个关键帧中 15 个落在稳定段（run 长度 ≥12 帧），只有 553/f110 是 1 帧瞬态。
   建议：v0.2 记录 `unique_state_id`（run 编号）与 `run_start/run_end`，稳定性判断以"同/不同唯一状态"为单位。
2. **目标不可见帧**：555/f140、556/f180 作为 approach 代表帧不合格（红色像素=0）。建议任何 ego-only 题目的
   每个 key frame 都要求目标至少可见（可用红/绿/蓝色 blob 面积做自动预检）并在可见性字段写证据。
3. **终态缺失**：1302 的 4 帧止于搬运中途，没有释放/入箱终态；若任务名声称 transfer，必须有关键帧覆盖终态。
4. **瞬态帧**：553/f110 是相机运动中的过渡帧；虽然标签值可接受，但用稳定帧（112/130）语义更干净。
5. **QA 图标签区**：模型输入图左上角烧有 `Current State` / `Next State N`；这对排序是必要的角色提示，
   但要在协议里注明它属于输入的一部分（当前 v0.1 文档没有写清，容易在复现时被误改）。

## 8. 对 v0.2 标注指南的具体建议

1. **三值化强制**：目标在该帧不可见时，关系必须标 `unknown`（不能被迫写 true/false）；`unknown` 帧不得作为
   可见转移端点。编译到 ENACT 场景图前，把涉及 unknown 的帧从 QA 路径中剔除（docs/06 §3 已有此要求）。
2. **可见性带证据**：visibility 记录 `value` + `evidence`（如目标色 blob 的像素数/bbox，或"不可见：目标色像素=0"）；
   支持 `partial`（被画面边界裁切/被夹爪遮挡 >50%）。
3. **谓词操作化定义 + 门槛**：
   - `OnSeabed`：可见接触点/紧贴阴影，或物体底部与海床间隙 < k px；否则 unknown。
   - `Lifted`：物体底部与海床有可见水柱/阴影分离，或"保持抓取 + 深度/压力单调上升"双证据；单帧不可判时 unknown。
   - `InGripper`：夹爪闭合 + 物体在钳口内（遮挡/夹持几何），并记录是否使用了辅助夹爪信号。
   - `NextTo`：按 §6 的 approach 语义，写进 schema 的 definition。
   - `InBox`：物体低于箱口边缘、静止于箱底、稳定 ≥N 帧；release 命令与"经过箱子上方"都不能替代。
4. **一个转移一个主变化**：编译动作文本前做 lint：若一个转移改动了 >2 个谓词，或文本出现矛盾子句
   （如 grasped + no longer next to），拒绝生成或强制拆分帧。v0.2 建议保留 `compile_action_descriptions` 的
   可读文本，但另存 `primary_change` 与 `secondary_changes` 供审计。
5. **L=5 的前置条件**：只有确实存在 5 个**可辨、稳定、目标可见**的语义状态时才用 L=5；
   若只有 4 个可辨状态（本组 4 条都只有 4 个），保持 L=4 并在 notes 说明。transf er 任务需要
   "抓起 / 升降 / 移到箱上 / 释放 / 入箱沉降" 这类真正可观察的状态，不能用悬停帧充数。
6. **关键帧唯一状态约束**：优先从 run-stable 段内取帧；同一 episode 内任意两个关键帧必须对应不同的唯一状态；
   连续帧之间的"变化"要在唯一状态序列上非空。
7. **ego-only 可判性元数据**：每个 changed relation 增加 `ego_only_visible`（基于两帧静态图是否可判）与
   `needs_aux_signal`；主结果只用 `ego_only_visible=true` 的转移，辅助信号结论另表。
8. **任务名/题面一致性**：QA 动作文本必须覆盖 task_text 声明的目标；若标签体系无法表达（如 1302 的 transfer），
   降级 task_text 或换 episode，不能只改名不改标签。
9. **保留 QA 生成与打乱记录**：v0.2 需像 v0.1 审计要求那样记录 seed/展示顺序与图片哈希（当前 QA 图的顺序可复算，
   但生成配置缺失），以便模型侧核对"模型看到的是哪些帧的什么顺序"。
10. **双相机**：wrist 视图对判断 release/入箱明显比 ego 更有信息（1302 的夹爪开合与箱内情况在 wrist 中更清楚）；
   若主协议坚持 ego-only，应把 wrist 辅助结论写入 `evidence_source`，不能混入 ego-only 分数。

## 9. 风险与未决问题

1. **NextTo 分歧的最终定性需要 Lead 统一口径**：本报告按"定义问题（both_acceptable）"处理；若 Lead 决定 v0.2 采用
   approach 语义，则 12 个分歧全部关闭，只需改文本模板。
2. **深度/压力信号的物理含义未确认**（`state[27]` 仅按相对深度代理使用）；本报告只用相对变化辅助判断"抓取后是否升离"，
   未把它当作真值。若该假设错误，不影响"标签值可接受"的结论，但影响 §0 第 5 条的表述。
3. **320×240 分辨率限制**：中间态 2–4 px 间隙/阴影无法可靠区分接触与微间隙；我的 Pass 1 对这类格判 undecidable，
   Pass 3 才用视频上下文 + 辅助信号接受原值。若 v0.2 要严判"ego-only 可判"，这些转移都应降级。
4. **仅复核 B 组 4 条**：A 组（200/201/552）的标签质量需 reviewer_a 结果合并；本报告只指出模型 3 处错误都在 ep000200。
5. **视频重复帧/场景跳变**：553/f134 附近有 1 帧内的明显场景跳变（相机快速运动/渲染更新），不是切镜，
   但说明"物理连续性"只能以唯一状态序列理解；v0.2 选帧时要避免把跳变帧当作稳定状态。
6. **wrist 相机只作辅助**；本组 1302 的最终入箱判定若需要更强的物理结论，建议接 Stonefish 真状态（路线 B），
   而不是继续从 RGB 外推。

## 10. 产物清单

| 路径 | 内容 |
|---|---|
| `pass1/usim_train_episode_{000553,000555,000556,001302}.json` | 盲评逐帧：4 关系 judgment+置信度+像素证据、对象可见性、稳定性/更佳帧 |
| `pass1/summary.json` | 盲评汇总（64 格：32 true / 25 false / 7 undecidable；16 帧稳定性；QA 图槽位映射） |
| `pass1/sha256.json` | Pass 1 写盘后哈希（之后才读 annotations） |
| `pass2_disagreements.json` | 逐帧对照、17 个关系分歧 + 2 个可见性分歧、12 个转移的编译动作文本与 ego-only 可判性 |
| `pass3_adjudication.md` | 24 项裁决表 + 1302 入箱专项 + 裁决分布 |
| `pass3/aux_lift_signal.json` | 夹爪 close/open 帧、压力峰/谷、辅助"升离起点" |
| `pass3/*.png` | 16 个 ±15/30/60 帧接触表（每格标注帧号/夹爪/压力） |
| `review_report.md` | 本文件 |
| `work/`（中间证据，非交付） | 预检、QA 图逐槽映射、红blob/阴影/相位相关探针、wrist 帧、10× 放大裁切等 |

（复核结论：v0.1 B 组标签**不能整体判为"已独立复核通过"**。物理过程判断基本正确，但存在 2 处明确 visibility 错误、
1 个必须版本化的 NextTo 语义缺陷、4 个关键帧选择问题，以及 8/12 个转移无法在严格 ego-only 静态图条件下确证；
1302 的 transfer 语义没有入箱证据支撑。建议按 §4/§8 修订后再进 v0.2。）


## 11. 交叉验证：与 reviewer-a / Lead 的 v0.2 裁决对齐（B 组）

本节为收到 Lead 补充说明后新增，使用 `observation.state[28]`（dvl_h，离底高度）重新核查；数据在
`work/dvl_h_crosscheck.json`。以下 4 个问题逐条回答。

### 11.1 OnSeabed 物理支撑语义：B 组 key3 应改为 true

| episode | key3 | close | key3 处 dvl_h | close 后 dvl_h 最小值 | 上浮起点（+10% 幅度） | key3 距上浮起点 | 结论 |
|---|---:|---:|---:|---|---:|---:|---|
| 553 | 168 | 149 | 0.2284 | 0.2173 @149 | 182 | +14（key3 在上浮起点之前） | **抓住仍贴底 → OnSeabed=true** |
| 555 | 297 | 278 | 0.2457 | 0.2444 @309 | 321 | +24 | 同上 |
| 556 | 339 | 319 | 0.2333 | 0.2333 @338（全局最小） | 362 | +23 | 同上 |
| 1302 | 196 | 176 | 0.2456 | 0.2419 @181 | 227 | +31 | 同上 |

与 A 组结论一致（reviewer-a：key3 的 dvl 离底高度最低、上浮起点在 key3 后 22–47 帧）。B 组上浮起点在
key3 后 **23–35 帧**（按 10% 阈值口径），同样说明 v0.1 在 key3 写 `OnSeabed=false` 是
"grasped ⇒ 离开海床"的模板推导，不是可见证据。该结论也与我 Pass 1 的"单帧不可判"一致：
ego 单帧只有 2–4 px 阴影间隙，无法区分贴底与微间隙；dvl_h 辅助信号给出了方向性证据。

补充：key4 的 Lifted 在 4 条上都成立（dvl_h 0.411/0.410/0.399/0.715，均远高于各自最小值），
说明 v0.1 的 Lifted 标签本身是正确的，问题只在 key3 的 OnSeabed。

### 11.2 NextTo 事件锚定：key2 相对 close 的偏移

| episode | close | key1（偏移） | key2（偏移） | key3（偏移） | key4（偏移） | 规范（§3.0）符合性 |
|---|---:|---:|---:|---:|---:|---|
| 553 | 149 | 110（−39） | 140（**−9**） | 168（+19） | 248（+99） | key2 比 close−15±5 窗口靠近 1 帧；key3 ✓ |
| 555 | 278 | 140（−138） | 262（−16） | 297（+19） | 377（+99） | key2 ✓、key3 ✓ |
| 556 | 319 | 180（−139） | 304（−15） | 339（+20） | 419（+100） | key2 ✓、key3 ✓（+20 上界） |
| 1302 | 176 | 150（−26） | 168（**−8**） | 196（+20） | 415（+239） | key2 比窗口靠近 2 帧；key3 ✓（+20 上界） |

结论：B 组 4 条的 key3 全部落在 close+10~20 的规范窗口内（+19/+19/+20/+20），**与 A 组同构，事件锚定成立**。
key2 有 2 条略偏近（553 −9、1302 −8，规范是 −15±5）：可以接受但应在 v0.2 迁移/新标中把 key2 推到
close−15 附近的稳定段（553 可用 f134–139 段内帧，1302 可用 f160–166 段内帧），
因为 −9/−8 时夹爪已明显贴近/包住物体（1302 在 f168 甚至已有一根手指在物体前方），
"approach 尚未抓住"的语义开始变得不纯。
key4 偏移：553 为 close+99、上浮起点后 +66（规范建议 40–60，略晚但更清晰）；555/556 为 +99/+100
（上浮起点后 +56/+57，符合）；1302 为 +239（transfer 任务，需在高处搬运，不能按 lift 窗口约束）。

### 11.3 逐帧 ego 可判性（yes/partial/no）

下表为 Pass 1 对每帧四条关系的"仅 ego 图能否判定"（yes=可判 / partial=部分可判 / no=不可判），
明细证据在 `pass1/*.json` 的 `ego_only_decidable` 字段：

| episode | 帧 | yes/partial/no | 不可判的关系 |
|---|---|---:|---|
| 553 | 110 | 1/1/2 | OnSeabed（接触点被画面下边缘裁切）、Lifted |
| 553 | 140 | 4/0/0 | — |
| 553 | 168 | 2/0/2 | OnSeabed、Lifted（2–4 px 间隙） |
| 553 | 248 | 3/1/0 | Lifted=partial（需两帧对比） |
| 555 | 140 | 0/1/3 | OnSeabed、Lifted、NextTo（目标不可见） |
| 555 | 262 | 4/0/0 | — |
| 555 | 297 | 2/1/1 | OnSeabed；Lifted=partial |
| 555 | 377 | 2/2/0 | OnSeabed/Lifted=partial |
| 556 | 180 | 0/1/3 | OnSeabed、Lifted、NextTo（目标不可见） |
| 556 | 304 | 4/0/0 | — |
| 556 | 339 | 2/1/1 | OnSeabed；Lifted=partial |
| 556 | 419 | 2/2/0 | OnSeabed/Lifted=partial |
| 1302 | 150 | 4/0/0 | — |
| 1302 | 168 | 1/2/1 | InGripper（闭合命令未发出，闭/开不可读）；OnSeabed/Lifted=partial |
| 1302 | 196 | 2/1/1 | OnSeabed；Lifted=partial |
| 1302 | 415 | 3/1/0 | Lifted=partial |

汇总：**完全可判的帧只有 6/16（553/f140、555/f262、556/f304、1302/f150 及可判性 4/4 的两帧）**；
`OnSeabed=false`、`Lifted=true` 这类"接触/间隙"变化在 320×240 ego 上普遍是 partial，
`InGripper` 的抓取变化基本可判（16/16 一致），`NextTo` 后置 false 属于定义问题而非可判性问题。

### 11.4 1302 的 key4=415：是否已上浮/接近箱口

- dvl_h 在 f415 = **0.7149**，是该 episode 全程接近最高值（max 0.7589）；上浮起点为 f227，
  即 f415 时已上浮约 188 帧、离底高度约为最小值的 2.96 倍 → **Lifted=true 成立**（物体随夹爪）。
- 但"接近箱口"的时机在 f415 之后：dvl_h 在 f435 降到 0.46（开始下降进入箱口），而 ego 画面在 f415 时
  绿箱在右前方、物体仍在箱子左侧。释放命令 f448、最后唯一画面 f454/f460 物体仍在夹爪/箱口近侧，
  无释放/沉降/落箱画面（详见 §5）。→ **1302 不满足 v0.2 L=5 transfer_inbox 路线**
  （规范 §3.1 已注明 1302 不满足）；也不满足 release_settle（没有落回海床的可见过程）；
  若采用 touching 路线则接触（Touching）在 ego 中不清（夹爪与物体在 320×240 下几乎重叠），不推荐。
  结论：1302 在 v0.2 中应保持 **L≤4（4 帧，pick-up 语义）**，或按 carry-to-box 重命名；
  不能作为 transfer_inbox 样本。

### 11.5 与 reviewer-a 结论的差异汇总

| Lead 采纳的 A 组结论 | B 组交叉验证结果 |
|---|---|
| key3 `OnSeabed` 应为 true（物理支撑） | **支持**：B 组 4/4 个 key3 同样应改 true（dvl_h 证据，§11.1） |
| NextTo approach 语义、key2=close−15±5 | **部分支持**：key3 全部在 close+10~20；key2 有 2 条（553/1302）偏离窗口 1–2 帧，建议微调 |
| 逐帧独立判断、禁止复制模板 | **支持**：7 条 v0.1 事实表完全同构（TFFF/TFFT/FTFF/FTTF），确属模板产物 |
| 关键帧取渲染保持段、相邻 ≥2 次更新 | **支持**：B 组 16 帧中 15 帧在稳定段，1 帧瞬态（553/f110）；相邻 key 的 run 间隔均 ≥20（556 的 304→339 为 28） |
| 红色游动物是小鱼不是红圆柱 | **支持**：本组检查中未把游动红色小目标当作目标物；503/555/556 的目标均为静止圆柱（红色 blob 形状/位置长期稳定）；v0.2 标注会显式排除小鱼 |
| 1302 不满足 transfer_inbox | **支持**：无释放/沉降/落箱可见证据（§5、§11.4） |
