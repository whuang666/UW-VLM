# ENACT × USIM v0.2 标注与关键帧规范（讨论稿 → 执行版）

版本：`usim-enact-v0.2`（草案 v1，2026-10-27）。项目：`E:\code\UW-VLM\ENACT`。
v0.1 原件只读保留；本规范只用于新增 episode 与 v0.2 数据构建。若与 v0.1 冲突，以本规范为准并在 v0.2 报告中列出差异。

## 0. 为什么需要 v0.2

v0.1（7 条 train episode / 28 帧 / 70 题）暴露的四个问题：

1. **L=3 无分辨力**：占 56/70，机会 EM=0.5（forward 的随机 PA 期望 0.625）。
2. **逆问题子可被文本先验完全解出**：程序化文本基线（只读题面动作文本、不看图）inverse EM = 35/35；模型去图条件 C 总体 0.7286 低于文本基线 0.7714。inverse 不能作为视觉能力证据。
3. **采样结构单一**：7 条轨迹全是同一抓取生命周期，同任务同场景族。
4. **标签未独立复核**；`NextTo` 语义在抓住后置 false 需要明确写进定义。

v0.2 的对策：扩 20 条开发/验证轨迹（另留 10 条 test 候选，冻结后才标注）；每条约 5–6 个可辨状态帧以支持 L=4/5；固定谓词定义与证据规则；题面与 conditions 版本化。

## 1. 数据范围与划分

| 集合 | 组成 | 用途 |
|---|---|---|
| dev | v0.1 的 7 条 + 新增 12 条 | 开发、prompt/参数选择 |
| val | 新增 8 条 | 选择与错误分析，不进入 test |
| test（预留） | 10 条候选（见 `_expansion/selection_manifest.json` 的 test_reserve） | **协议冻结后才标注**，不参与任何选择 |

- 只用外层 USIM `train/`；外层 `test/` 525 条全程不参与标注、选择或调参。
- 划分按 episode（轨迹）而非按题；同一 episode 的所有方向、长度、图片版本属于同一集合。
- 划分在 `_expansion/annotation_assignment.json` 预登记，标注阶段不得改。

## 2. 词表与谓词定义（v0.2 固定）

沿用上游 ENACT 谓词名以兼容 translator/verifier；v0.2 在文档和 `notes` 中固定语义。

### 2.1 单目谓词（node state）

| 谓词 | v0.2 定义 | 证据要求（ego-only） | 明确不算 |
|---|---|---|---|
| `OnSeabed(obj)` | 物体被海床/沙面支撑，未被夹持或悬空；**被夹住但仍贴底时仍为 true**（物理支撑语义，v0.2 修正） | 物体与海床接触可见（底部贴地、无可见间隙、无下方阴影分离）；运动静止；dvl 离底高度（`state[28]`）只作辅助 | 仅“位置低”；**“已抓住 ⇒ OnSeabed=false”的模板推导（v0.1 错误）** |
| `InGripper(obj)` | 夹爪实际持有物体（闭合且物体随末端运动） | 夹爪—物体接触可见 + 相邻帧共同运动；夹爪信号仅辅助（close 命令可早于实际抓住 10–40 帧） | 仅夹爪闭合信号；仅机械臂靠近 |
| `Lifted(obj)` | 物体被持有且最低点明显离开所在海床（有可见间隙，约 ≥ 物体半宽） | 物体与海床之间可见间隙；dvl_h / pressure 可辅助但不单独作准；取离底起点后 40–60 帧的稳定帧 | 只是离开海床几像素的抖动；夹住但仍贴底 |
| `InBox(obj)` | 物体在绿箱内部、已释放并稳定 | 箱壁/箱口内可见物体，释放后稳定 ≥8 帧（10 Hz） | 悬停在箱口上方、仅朝箱移动、释放后未沉降 |

### 2.2 二元关系

| 关系 | v0.2 定义 | 证据要求 | 明确不算 |
|---|---|---|---|
| `NextTo(robot,obj)` | **接近阶段**：机器人末端接近物体、尚未抓住；抓住后恒为 false | 末端靠近物体、夹爪尚未持有；transition 与“抓取前”一致 | 纯几何距离；“机器人一直在物体旁边” |
| `Touching(robot,obj)` | 末端/夹爪与物体有可辨识接触，但尚未持有 | ego 图中可见夹爪与物体接触（通常 ±5 帧内）；夹爪信号辅助 | 仅“很近”；看不清接触时不标（从 scope 移除） |
| `NearBox(robot,green_box)` | **at-box 释放位置**：机器人/末端在绿箱释放位置附近、物体仍被持有（用于 transfer 的 L=5 替代状态） | 绿箱在 ego 中可见；机器人与绿箱的相对位置较携带段明显改变；稳定帧 | 不能替代 InBox（物体没有可证入箱）；箱不可见时不标 |

**`NextTo` 说明（v0.2 关键约定）：** 这是“approach”语义而非纯距离；一个帧里机器人物理上靠近物体但已抓住时，`OnSeabed=false`、`InGripper=true`、`NextTo=false` 同时成立是**符合定义**的。标注 notes 必须写明本 episode 采用该定义。

### 2.3 每个任务的 scope（只标注 scope 内且所有关键帧都能判定的谓词）

- `pick pipe` / `pick blue` / `pick red` 基础 scope：
  `OnSeabed(target)`、`InGripper(target)`、`Lifted(target)`、`NextTo(robot,target)`。
- 若采用 `touching` 路线支持 L=5，额外加 `Touching(robot,target)`（仅当每一关键帧都能清晰判定；否则整条 episode 不加）。
- `transfer` 任务：基础 scope + `InBox(target)`；`objects` 增加 `green_box`（`category: box`, `color: green`），每帧给绿箱可见性。只有确实观察到最后稳定在箱内才允许 `InBox` 在末帧为 true；否则 `InBox` 不进入 scope（不能逐帧 null）。
- 不允许逐帧 unknown：编译器拒绝 null。某谓词不能在全部关键帧判定时，把该谓词从整条 episode 的 scope 移除。
- 同一 episode 只标 1 个被操作目标；画面中的其它同类物（干扰物）不建模，但 notes 要说明指代依据（颜色/位置）。

## 3. 关键帧选择规则

目标 **5 个关键帧（L=5 需要 5 状态/4 个可辨转移）**；若确实存在第 6 个可辨状态（如 carry→release→settle），可标 6 帧。若只有 4 个可辨状态，就标 4 帧（该 episode 只能支持 L≤4，必须在 notes 注明原因）。

硬性规则（每条都必须满足）：

1. **稳定状态帧**：该帧前后 ≥10 帧内画面基本静止（USIM 是低帧率渲染，常有 8–14 帧重复画面；用 package 的 `stability`/`motion` 证据），不能取在运动/模糊/过渡中。
2. **单调且有语义差异**：相邻关键帧之间必须有可判定的谓词变化（diff 非空），不得靠换帧号凑长度。
3. **ego-only 可判**：每个转移必须能只看 ego 帧对判定；只能靠腕相机/关节信号判断的变化不得作为主结果标签（wrist 仅可作辅助确认，需在 notes 记录）。
4. **物体可见**：每个关键帧中目标物体可见（visibility=true）；不可见的帧不能作为关键帧。
5. **禁止用时间戳/帧号/模型输出选帧**：选帧只能依据画面内容、稳定性与事件顺序。
6. **每个转移在题面中必须可见且非空**：构建完成后用 `annotate_episode.py --check` 与 build 后的 oracle 验收（oracle 必须 1.0；空签名会被评分 gate 拒绝）。

### 3.0 事件锚定与渲染保持（2026-10-27 复核新增，必须遵守）

复核发现 v0.1 的关键帧与夹爪事件严格同构（key2≈close−15、key3≈close+20），且 ego 视频是渲染保持式（每条 episode 仅 35–42 个唯一画面，每个保持 8–14 帧）。因此选帧必须事件锚定并记录保持段：

- **key2（approach/NextTo=true）**：夹爪 close 事件前 **15±5 帧** 的稳定帧，且 `InGripper=false`、`OnSeabed=true`。close 事件可从 package 的 `gripper.events` 取。
- **key3（grasp/InGripper=true）**：close 之后 **+10~+20 帧** 的稳定帧；此时物体通常仍贴底 → `OnSeabed=true`、`Lifted=false`；只有画面出现可见离底间隙才允许 `OnSeabed=false`。
- **key4（lift/Lifted=true）**：dvl 离底高度开始上升（ascent onset）之后 **40–60 帧**、ego 可见离底间隙（≥ 物体半宽）的稳定帧；package 的 `gripper`/`state_summary` 与信号只作辅助。
- **key1（start）**：key2 之前、机器人尚未接近（`NextTo=false`）、物体在 seabed 上且可见的稳定帧。
- **相邻关键帧至少相隔 2 个渲染更新（≥20–25 帧）**；记录每帧所在保持段（run start/end 或唯一画面索引）。不要用 ±10 帧邻域"看起来稳定"当作信息量证据。
- L=5 的第 5 帧（transfer_inbox / release_settle / touching）同样遵循上述稳定帧规则。

### 3.1 L=5 的可选路线（按优先级）

2026-10-27 全量扫描结论（见 `docs/WBW/ENACT-USIM-扩展候选与工具-20261027.md` §3.3/§4）：
transfer 块 100/100 条在结束前 16–18 帧释放，释放后目标质心均未进入绿箱 bbox、无沉降 → **`InBox` 在 ego-only 下不可证，禁止使用**；pick 轨迹选中样本结束时仍持有 → `release_settle` 也不可用；`touching` 因 close 早于实际抓取且渲染保持使 touch/grasp 常同一画面，不能默认成立。
因此 v0.2 主线按 **L≤4** 建题；仅当下面第 0 条证据齐全时允许 L=5：

0. **at_box（transfer 专用，v0.2 唯一的 L=5 通道；Lead 已于 2026-10-27 批准）**：
   start(on seabed) → approach(NextTo obj) → grasp(InGripper) → lift(Lifted) → at_box(**NearBox(robot,green_box)** 且物体仍 Lifted/InGripper=true)。
   要求：绿箱在每个关键帧可见；at_box 帧取**首次 release 事件前 15±5 帧**、稳定渲染保持段内（≥8 帧）、物体仍被持有（夹爪闭合信号高位）；机器人与箱相对位置在携带段后有可见变化；**不得**同时声称 InBox。
   2026-10-27 抽查结论：1304/1318/1357 满足（L=5），1330 缺 start 帧只能 L≤4；独立抽查见 `data/usim_enact/_expansion/annotation_work/reviewer-a/crosscheck/transfer_at_box_check.{json,md}`。若 at_box 证据不足，退回 4 帧。
1. **transfer_inbox**：需真实入箱并稳定 ≥8 帧；当前 100 条 transfer 均不满足 → v0.2 不启用。
2. **release_settle**：物体离开夹爪并落回海床（OnSeabed 回 true、InGripper/Lifted 移除）；选中样本均无最终 open 事件 → 暂不可用。
3. **touching**：start → approach → touch(Touching) → grasp → lift；只有 ego 中接触**清晰可辨**且稳定帧独立于 close/grasp 渲染段时采用；否则退回 L≤4。

不满足任一 L=5 路线的 episode 标 4 帧，仅生成 L=3/4 题；不要用悬停重复帧或“动作进行中”帧充数。

## 4. 标注产物与格式

每条 episode 一个 JSON（`USIMEpisodeAnnotation` 格式，可直接被 `build_dataset.py` 编译）：

- `protocol_version`: `"usim-enact-v0.2"`
- `episode_key`: `usim_train_episode_XXXXXX`（train split；v0.2 不标 test）
- `source_split`: `"train"`；`episode_index`、`task_index`、`task_text` 从 `usim/train/meta/episodes.jsonl` 取
- `label_source`: `"agent_visual_review"`；`annotation_status`: `"reviewed"`
- `notes`: 写清 (a) NextTo 定义采用 approach 语义；(b) 每个关键帧的角色（start/approach/…）；(c) L=5 路线或“仅 4 状态”的原因；(d) 干扰物指代依据；(e) 任何辅助证据（wrist/关节信号）与其用途
- `objects`：`robot` + 目标物（+ transfer 的 `green_box`）
- `relations`：见 §2.3；**只含所有关键帧都可判定的谓词**
- `frames`：按 frame_index 升序；每帧给出 `facts`（scope 全量、value 为 bool）、`visibility`（每个对象一项）、可选 `note`
- `visibility.method`: `"agent_visual_review"`（不伪造像素数/bbox）

工作副本（spec/notes/接触表）写在各自 `data/usim_enact/_expansion/annotation_work/<annotator>/<episode>/`，不写进 v0.2 正式目录；正式 JSON 由 Lead 汇总/抽检后入 `usim-enact-v0.2/annotations/episodes/`。

## 5. 标注流程（每条 episode）

1. 读 `_expansion/packages/<episode>/package.json` 与接触表（`sheet_candidates.png`、`sheet_timeline.png`、`sheet_candidates_wrist.png`），对照 `usim/train` 原视频。
2. 先**独立看帧**形成初始判断，再看 package 的 `predicates_hypothesis`（它是提议，不是真值）。
3. 在 package 候选帧附近 ±10–20 帧找稳定帧；必要时自己抽帧（`annotate_helper.py --frames`）。
4. 定 5（或 6/4）个关键帧与每帧 facts/visibility；写 spec JSON。
5. 用 `python -m scripts.usim.annotate_episode --spec <spec> --out <draft.json> --check` 校验；校验必须显示 scope 完整、转移非空、无 unknown。
6. 写 `notes.md`：逐帧角色、证据（帧号/现象）、L=5 路线、不确定点、wrist/信号辅助使用情况。
7. 回报 Lead：episode、帧号列表、L 路线、l5 是否成立、风险。

## 6. 验收与抽检

- 机械验收：`annotate_episode --check` 全部通过；`build_dataset.py` 能编译；oracle 全对。
- 人工抽检：Lead 对每个 annotator 抽 ≥1 条（覆盖 pick/transfer）复核帧序、facts、visibility；分歧记录后由 Lead 裁决。
- 任何标签/帧改动 → 改 version patch（如 v0.2.1）并重跑 oracle/基线；不改已冻结的 v0.1。
- `NextTo`/`Touching`/`InBox` 定义一旦冻结不得在 run 中途改动。

## 7. 与 v0.1 的已知差异（需在报告中列出）

1. 新增轨迹与场景变体（不同采集批次）。
2. 关键帧从 4 → 5/6（按 L=5 路线），题集长度分布改变。
3. `NextTo` 语义显式化（approach，非几何距离）；`Touching`/`InBox` 按证据启用。
4. 题集构建将做**长度分层配额**（L=3 少、L=4/5 多），并以 forward 作为主要视觉指标（理由见评估方案）。
5. **v0.1 七条 episode 迁入 v0.2 时修正 `OnSeabed` 三值语义**：抓住但仍贴底 = true（7 条各 1 处 key3 修正；证据 dvl 离底高度在 key3 处最低、上浮起点在其后 22–47 帧；见 `_review/round2/reviewer_a/review_report.md` M1–M3 与 `usim-enact-v0.2/migration_v01_to_v02.json`）。迁移后 7 条仍为 3 个可见转移（L≤4）。
6. 动作文本：`NextTo` 的模板改为 "in position for the pre-grasp approach beside"，消除 "grasped … no longer next to" 的自然语义矛盾；`Touching` 模板改为 "in contact with"（`enact/adapters/usim_translator.py`）。文本先验基线需按新模板更新正则。

## 8. 独立复核裁决（2026-10-27，写入执行规范）

来自 `_review/round2/reviewer_a` 的正式复核结论（B 组 reviewer_b 待汇总），对 v0.2 的强制要求：

1. **`OnSeabed` 用物理支撑语义**（见 §2.1）：被夹住但仍贴底时必须为 true；v0.1 的 "grasped ⇒ OnSeabed=false" 是模板推导，不是视觉证据，v0.2 禁止。
2. **`NextTo` 用事件锚定窗口**（见 §3.0）：`NextTo=true` 只取 close−15±5 且 `InGripper=false`、`OnSeabed=true` 的稳定帧；抓住后恒 false；`Touching` 若启用也必须事件锚定且 ego 可见接触，否则会与 NextTo 混淆。
3. **关键帧取渲染保持段内的稳定画面**，并记录保持段；相邻关键帧至少间隔 2 个渲染更新（§3.0）。
4. **逐帧独立标注**：不得从其它 episode 复制事实表；7 条 v0.1 episode 的"4×4 完全同构事实表"是模板产物，v0.2 新轨迹必须逐帧给出证据与 ego 可判性（notes 记录 yes/partial/no）。
5. **notes 事实核对**：红色游动物体是**小鱼**不是红圆柱；蓝色圆柱在 ego 中偏紫，description 保留 "blue cylinder (purple appearance in ego)"。每个 episode 写清目标物指代依据与干扰物。
6. **已知限制（如实报告）**：v0.2 新增标注为 1 名标注者 + Lead 抽检（不是双人独立标注）；ego-only 对距离/接触/离底判定存在 partial 情况，报告必须把 "ego 可判性" 与 "标签值" 分列。
7. **动作文本仍由状态差分生成**：inverse 文本先验不会因模板措辞完全消失；v0.2 报告必须附程序化文本基线（`scripts/usim/text_prior_baseline.py`，需按新模板更新）与条件 C。
