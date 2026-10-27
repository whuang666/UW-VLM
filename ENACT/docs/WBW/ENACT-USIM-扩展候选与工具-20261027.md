# ENACT-USIM v0.2 扩展候选与工具（task-3 交付报告）

日期：2026-10-27（Asia/Shanghai）。执行者：data-engineer。任务：`task-3`（扩展候选选择、取证与标注工具）。
关联任务：`task-10`（v0.2 transfer 标注批 E，见 §7 后续工作）。
规范依据：[v0.2 标注与关键帧规范](../WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)、[水下适配方案](../04_underwater_adaptation.md)、[数据与评测契约](../06_data_and_evaluation_contract.md)。

## 0. 结论摘要

1. **候选 30 条已选定并全部取证**：13 个操作任务块 × 2 条（24 条 pick：pipe/blue/red 各 8）+ transfer 块 6 条；固定 seed `20261027`，二次运行 `selection.jsonl` SHA-256 与 `selection_manifest.json` 均逐字节一致。
2. **30 个标注就绪包全部生成**：每包 3 张接触表（candidates 4 列带帧号/角色、timeline、wrist 辅助），`package.json` 含夹爪事件、action/state 摘要、motion burst、4–6 候选关键帧、±10 帧稳定性检查、颜色 blob 证据、L=5 路线候选与逐转移证据。
3. **标注工具 `annotate_episode.py` 已交付并通过端到端验收**：spec→合法标注→`USIMEpisodeAnnotation.validate()`→转移非空检查→`build_dataset.py` 编译 5 帧/4 转移全部 visible；`--check` 对 v0.1 七条输出 28 帧/21 转移/21 visible。
4. **L=5 结论（关键，负结果）**：在现有 ego 视频与既有谓词下，**本批 30 条候选没有一条能干净支持 L=5**。
   - transfer 的 `transfer_inbox` 路线**全部失败**：对 transfer 全块 100 条逐条扫描，释放事件都发生在视频结束前仅 16–18 帧；释放后目标物体在 ego 中仍停留在夹爪/箱口位置，**100/100 条其颜色质心都不在绿箱 bbox 内**（cx≈91–114，箱 bbox 左沿≥112–202），没有任何一条出现“释放后沉降进箱并稳定 ≥8 帧”的证据。1302 的结论在整批中成立。
   - pick 的 `release_settle` 路线不可用：24/24 条选中 pick 在视频结束时夹爪仍闭合、物体仍被持有（无最终 open 事件）。
   - pick/transfer 的 `touching` 路线证据弱：23 条候选有 close 附近接触候选帧，但 close 命令常早于实际抓取 10–40 帧且接触帧与 grasp 帧仅相隔 1–2 个渲染段，ego 可辨性未达 v0.2 “清晰可辨”门槛，只能逐条复核、不能作为默认 L=5。
   - 因此建议 v0.2 主线按 **L≤4** 建题：27 条候选有 4 个可辨状态（L=4），3 条只有 3 个（980/1135/1330，见 §5.3）。若要 L=5，需 Lead 对协议做一次明确决策（§5.4 给出两条可行路线，其中 `NextTo(robot, green_box)` 复用现有词表、不需要新增谓词）。
5. **给 v0.2 指南的具体修正建议**：transfer 的 InBox 不应作为 L=5 的默认路线；`OnSeabed` 物理支撑语义需要在 package/标注里同步（grasp 帧常为 true）；选帧应使用事件锚定 + `state[28]`（dvl 高度）上升起点；transfer 的第 5 状态若启用，优先用 `NextTo(robot, green_box)`（at-box）而不是 InBox（详见 §6）。

## 1. 交付物

| 交付物 | 路径 | 说明 |
|---|---|---|
| 选片脚本 | `ENACT/scripts/usim/select_episodes.py` | 读 train meta → 20 块 → 30 候选 + manifest；固定 seed，可复跑 |
| 选片结果 | `ENACT/data/usim_enact/_expansion/selection.jsonl` | 30 行（episode_key/task/block/length/夹爪事件/L5 flags） |
| 选片 manifest | `ENACT/data/usim_enact/_expansion/selection_manifest.json` | 规则、seed、排除统计、20 块表、任务×块分布、输入与输出哈希 |
| 取证包脚本 | `ENACT/scripts/usim/build_episode_package.py` | 30 包 + `packages/index.json`；含 `--reindex` 免重建重建索引 |
| 取证包 | `ENACT/data/usim_enact/_expansion/packages/usim_train_episode_*/` | 每包 `package.json` + 3 张 PNG；索引 `packages/index.json` |
| 标注生成/校验脚本 | `ENACT/scripts/usim/annotate_episode.py` | spec→合法标注；`--check` 打印每 episode 转移/可见转移；`--verify-frames` |
| spec 模板 | `ENACT/data/usim_enact/_expansion/tools/annotate_spec_template.json` | transfer 5 帧示例（含 green_box、InBox） |
| 工具一页用法 | `ENACT/data/usim_enact/_expansion/tools/annotate_episode_usage.md` | 命令与字段规则 |
| 端到端 smoke | `ENACT/data/usim_enact/_expansion/smoke/` | spec→标注→`build_dataset.py` 编译证据（5 帧/4 转移全 visible） |
| 目视复核材料 | `ENACT/data/usim_enact/_expansion/probe/transfer_review/` | 6 条 transfer 的释放前后 full/zoom 接触表；InBox 100 条扫描结论由此得出 |

固定哈希（复跑验证）：

```text
selection.jsonl        sha256 = 9c408fb9677cf19de77bbecc936b8a4fc422c0d37132b66a6b563b10aba1eeb4
selection_manifest.json sha256 = 2b4d0fe89e2829c32fffa47b6ad6c3a4cb0717991305fdde4eadd281c230595b
```

## 2. 选片规则与结果

### 2.1 数据事实

- 只用外层 `usim/train`（1,750 条）；外层 `usim/test` 525 条全程排除（选择/阈值/prompt 均不接触）。
- v0.1 已用 7 条排除：200/201/552/553/555/556/1302（脚本同时读取 v0.1 annotations 目录交叉核对）。
- 长度过滤 150–700 帧（10 fps → 15–70 s）；全库 42–827 帧，1,628 条在区间内。
- 任务块：`episodes.jsonl` 相邻 tasks 相同的连续段共 **19 段**；其中 `Pick up the red cylinder` 有一段 200 条，而 `episode_frame_summary_lerobot_train.csv` 声明四个 red 子目录各 100 条，因此在 100 条边界拆成 2 块 → **20 块**（推断，已写入 manifest 的 `block_split_inference`）。
- 操作类任务块 13 个（pipe×4、blue×4、red×4、transfer×1）；非操作块 7 个（charge/scan×2/inspect×2/follow/water）排除，理由写入 `exclusions.non_manipulation_blocks`。

### 2.2 配额与策略（按 Lead 指示）

| 块类型 | 配额 | 策略 |
|---|---:|---|
| transfer（1300–1399） | **6** | 要求最终 open 事件且释放后 ≥8 帧；记录末帧绿箱 blob 面积；分 tier 接受，tier 记录在 `selection_strategy` |
| 其它操作块 | 2/块 | slot A 优先搜“最终释放且有 ≥8 帧沉降”的 episode（25 条内扫描）；slot B 为确定性随机抽取；均按 block RNG |
| 补齐 | 记录 | 若不足 24 条才从相邻块补齐，`fill_events` 记录原因（本次未触发） |

固定 seed `20261027`；块内 RNG = `random.Random(f"{seed}:{block_id}")`，slot B 为洗牌后的下一次抽取。复跑哈希一致（见 §1）。

### 2.3 结果分布

```text
Pick up the pipe                                   : train_b02=2, b10=2, b13=2, b20=2   (8)
Pick up the blue cylinder                          : train_b03=2, b07=2, b12=2, b15=2   (8)
Pick up the red cylinder                           : train_b08=2, b09=2, b14=2, b18=2   (8)
Pick up the red cylinder and transfer it to the box: train_b16=6                        (6)
合计 30；supports_l5_candidate（信号级）：6（全部 transfer）
```

共 30 条；13 块 / 20 块 = 65% 的操作任务块被采样，且每块最多 2 条（transfer 例外 6 条），避免同一采集批次过度集中。

## 3. 取证包

### 3.1 包结构

```text
packages/usim_train_episode_XXXXXX/
  package.json
  sheet_candidates.png        # 4 列，帧号+角色（start/approach/touch/grasp/lift/carry/release_settle/end）
  sheet_timeline.png          # 4 列，8 帧等距，用于场景/背景复核
  sheet_candidates_wrist.png  # 4 列，同帧腕相机（仅辅助证据；协议输入仍 ego-only）
```

`package.json` 主要字段：

- `episode_key/source_split/episode_index/task_index/task_text/block_id/block_range/length/fps/duration_seconds`；
- `source_files`：parquet/ego/wrist 路径与 SHA-256、parquet 行数与 ego 解码帧数；
- `gripper`：`observation.state[0]`（joint_pos[0]）信号，阈值 0.004，close/open 事件帧+时间戳，`final_state`、`frames_after_final_open`；
- `state_summary`/`action_summary`：按 modality.json 切片（joint_pos/pwm/joint_v/dvl_v/imu_av/imu_la/pressure/dvl_h）的均值/方差/最值；
- `motion`：相邻 ego 帧灰度差分的均值/p95/max 与 top-5 burst 帧；
- `candidate_frames`：每帧 role、时间戳、证据串（含与 close/release 事件的帧偏移、目标 blob 面积/质心、箱 blob、稳定性摘要）、`stability`（±10 帧窗口采样、motion 均值/阈值、目标出现率、质心漂移、最近事件、`stable`/reasons）、`target_blob`、`box_blob`；
- `target_tracking`：颜色分量法说明、同色歧义帧列表；
- `sheets`：三张接触表路径/SHA-256/帧号；
- `scene`：启发式背景描述（mean BGR/HSV、edge density、`bright_shallow_like`/`dark_factory_like`/`ambiguous` 提示，**未验证**）；
- `l5`：路线候选（transfer_inbox / transfer_at_box / release_settle / touching / none），每条含 states（帧号+谓词假设向量）、transitions（changes+证据串）、requirements、risks、`num_distinguishable_transitions`；`l_max_states_baseline`/`l_max_states_optimistic`；
- `annotation_brief`：建议 objects/relations、L=4/L=5 建议关键帧角色与风险（**只是提案，不是标注**）。

### 3.2 统计

- 30/30 包成功；0 个解码错误；175 个候选帧中 136 个通过 ±10 帧稳定性检查（39 个被标 unstable，多为事件附近/快速移动帧，属预期），2 条包全部候选帧 stable。
- 候选帧数：5 帧 ×4 条、6 帧 ×26 条（4–6 范围内）。
- 1 条包有同色歧义 warning（287，蓝任务有多个紫色分量），其余 29 条无 warning。
- 场景提示：29 条 `bright_shallow_like`、1 条 `ambiguous`（628）；**未出现 `dark_factory_like`**——该分类器基于亮度阈值，需在 v0.2 前用真实 shallow/factory 对照校准，当前只能当提示。
- 夹爪事件：transfer 全部“close →（可选 retry）→ open(视频末)”模式（释放距末帧 16–18 帧）；pick 24/24 只有 close（视频结束仍持有）；pick 中有 4 条含 retry 模式（297/980/1259/1304 等多次 close/open）。
- target blob 检测：蓝色圆柱在 ego 中偏紫，`annotate_helper` 的 blue 区间会先命中水体/背景，包内改用紫色偏置区间 + border/oversize/上 1/3 过滤；红色物体存在“小鱼/干扰物”风险，包内只取最大非边界分量并记录 `ambiguous` 计数，**指代仍需人工复核**（规范 §8.5）。

### 3.3 目视抽查记录（≥3 条，实际 6 条 + 100 条扫描）

| episode | 任务/块 | 结论（状态是否可辨 / 背景） | 证据 |
|---|---|---|---|
| 1304 transfer b16 | 6 帧：[136 start, 152 approach, 244 grasp, 360 lift, 481 carry, 511 release_settle] | 前 4 状态（seabed→approach→grasp→lift）在 ego 可辨；carry 时绿箱显著增大；release_settle 帧物体仍在夹爪/箱口，**不能判 InBox**；背景亮沙地（shallow-like） | `sheet_candidates.png`、`probe/transfer_review/full_001304.png` |
| 1318 transfer b16 | [64, 220, 275, 393, 517, 547] | 同 1304；release 后 16 帧红物体始终在夹爪位置，箱内不可见沉降 | `probe/transfer_review/full_001318.png`、`zoom_001318.png` |
| 1330 transfer b16 | [80, 88, 107, 223, 344, 374] | 物体直到 f80 才可见，start≈approach（8 帧差）不独立 → 只有 3 个可辨状态；InBox 不成立 | `full_001330.png`/`full_001330_endcheck.png` 等 |
| 1397 transfer b16（扫描样本） | 释放 f453，箱 bbox=[112,101,208,139]，红质心 (106,122.9) | 箱口在画面内、物体停在夹爪/箱口上方，16 帧内无下落；`inside_last=false` | `probe/transfer_review/full_001397_endcheck.png` |
| 287 pick-blue b03 | [208, 287, 329, 342, 419, 440] | 紫色圆柱在海床→接近→夹持→提起 4 状态清楚；touch/grasp 两帧视觉差异小（touching 路线弱）；背景亮沙地 | `sheet_candidates.png` |
| 104 pick-pipe b02 | [187, 237, 279, 292, 363, 384] | 灰色管道 4 状态可辨（无颜色证据，靠 motion/机器人姿态）；背景亮沙地 | `sheet_candidates.png` |
| 587 pick-red b08 | [168, 199, 243, 254, 311] | 红圆柱 4 状态可辨；顶部有暗色结构（factory-like 背景），说明场景变体存在 | `sheet_candidates.png` |

**InBox 专项扫描**：对 transfer 全块 100 条逐条取释放帧/释放后 5/10/15 帧与末帧，计算红色目标质心与绿色箱 bbox 关系：**100/100 条 `inside_last=false`**，红目标质心 cx 91–114、箱 bbox 左沿 112–202，距离箱中心 119–199 px；释放后目标位置基本不动（无下落）。→ 本批 transfer **没有可用 InBox 证据**。

## 4. L=5 可行性分析

v0.2 要求 L=5 = 5 个稳定状态 / 4 个可辨转移，三条路线按优先级：`transfer_inbox` > `release_settle` > `touching`。

### 4.1 路线逐条结论

| 路线 | 本批证据 | 可用性 |
|---|---|---|
| transfer_inbox | transfer 100/100 条：释放距末帧仅 16–18 帧；释放后物体仍停在夹爪/箱口，质心全部在箱 bbox 外；无“箱内稳定 ≥8 帧”画面 | **不可用（0/100）** |
| release_settle | 24/24 选中 pick 视频结束时仍持有（无最终 open 事件）；transfer 释放后物体留在箱口高度，未见落回海床 | **不可用（0/24 pick，transfer 亦不成立）** |
| touching | 23/30 候选在 close 附近存在接触候选帧；但 close 常早于实际抓取 10–40 帧，且 USIM 渲染保持使 touch 与 grasp 常落在同一/相邻唯一画面，ego 清晰可辨性不足 | **弱候选；需逐条目视复核，不能默认 L=5** |

### 4.2 逐候选最大 L（严格 v0.2 口径）

| 结论 | 数量 | episodes |
|---|---:|---|
| L=4（4 个可辨状态：start→approach→grasp→lift） | 27 | 除下面 3 条外的全部 |
| L=3（start/approach 或 approach/touch 不可分） | 3 | 980（approach 与 grasp 合并）、1135（无 touch 候选/路线 none）、1330（物体 f80 才可见，start 缺失） |
| L=5（严格口径） | **0** | — |

> 注：`l_max_states_optimistic` 在 23 条 pick 上给出 5，是“若 touching 路线被复核接受”的乐观值；**不是当前可交付的 L=5**。

### 4.3 任务/轨迹层面的 L=5 判断

- **pick pipe / blue / red**：生命周期只有 4 个稳定状态（seabed→approach→grasp→lift，grasp 帧按物理支撑语义 OnSeabed 仍可为 true）。没有最终释放 → 无第 5 状态；touching 路线是唯一理论可能，但本批 24 条均无“清晰可辨的接触态”证据链。→ **L≤4**。
- **transfer**：本来唯一干净 L=5 路线是 InBox，但本批渲染/数据在释放后不表现沉降，**InBox 不可证**。若 Lead 允许“at-box（携带到箱上方、尚未释放）”作为第 5 状态，transfer 的 6 条中有 4–5 条在 carry 帧有清晰“绿箱充满画面+机器人末端在箱上方”的 ego 证据（1304/1318/1357/1378/1384；1330 也可见但前段状态不足），见 §5.4。

### 4.4 若必须 L=5：两条可选路线（需 Lead 决策，未改词表/未改协议）

**路线 A（推荐，零新增谓词）：transfer 增加 `NextTo(robot, green_box)` 作为 at-box 第 5 状态。**
- 语义：机器人末端携带目标到达绿箱上方/箱口（释放前），`NextTo(robot, green_box)=true`；抓取目标后 `NextTo(robot, target)` 仍为 false（v0.2 approach 语义不受影响）。
- 最低证据（ego-only）：绿箱在画面内且箱口/箱沿可见、机器人末端位于箱口上方（2D 投影在箱 bbox 上方或重叠）、对象仍被持有；相邻帧箱 bbox 面积显著增大（如 1304 f481 绿箱面积 4231 vs lift 帧 1153）。
- 不可替代信号：不能用 InBox 代替（对象并未入箱）；也不能只靠“向箱移动”的关节/动作信号。
- ego-only：**可以**判定（箱与末端均在 ego 内），但需要一个“到达箱上方”的明确距离/投影阈值，需写入协议。
- 风险：`NextTo` 当前定义为“接近目标物、抓住后为 false”，用于 box 目标需在协议中显式写明是 goal-approach 语义；且这是 carry 阶段状态，不是任务完成语义。若 Lead 批准，可产出 start/approach/grasp/lift/at_box 5 帧、4 个可见转移。

**路线 B（逐条复核 touching）：** 仅在 ego 中“夹爪接触物体但尚未持有”清晰可辨的 episode 上启用 `Touching(robot,obj)`；需要明确“接触可见”的可操作判据（夹爪末端与物体 bbox 重叠 ≥N 像素 + 相邻帧无共同运动），且必须逐条复核。本批证据不足以批量启用。

**若坚持新增谓词（不推荐在本批执行）**：候选 `OverBox(object, green_box)`（物体悬于箱口上方）或 `CarryAtBox(robot, green_box)`；前者对象在箱口投影内且与箱底有可见间隙，后者末端在箱上方且目标仍被持有；二者都只能由 ego 判定（箱可见时）；不能替代 InBox；需改词表 + translator 模板 + 重新冻结版本。**结论：本批优先用路线 A 的现有 `NextTo`，不建议直接扩展词表。**

## 5. 标注工具 `annotate_episode.py`

### 5.1 能力

- `--spec`：读取紧凑 spec（objects/relations/frames facts/visibility_default），自动填 `timestamp_seconds`，校验帧号在 episode 范围内；
- 展开为完整 `USIMEpisodeAnnotation` 并调用 `validate()`：scope 完整性（每帧 facts 必须恰好覆盖 relations）、无 unknown、帧升序唯一、每个对象每帧都有 visibility；
- 检查每对相邻关键帧转移非空（v0.2 硬性规则），空转移直接 exit 1；
- `--check --annotations <dir>` / `--annotation <file>`：校验已有标注并打印每 episode 的 key frames / transitions / visible transitions / 转移文本；
- `--verify-frames`：逐帧解码 ego 视频，确认关键帧可读；
- `--out/--out-dir/--dry-run`：只写工作副本；不会写 v0.1/v0.2 正式目录。

### 5.2 验收命令（已实跑）

```powershell
Set-Location E:\code\UW-VLM\ENACT
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'

# 1) v0.1 回归：7 条 × 4 帧 / 3 转移 / 3 visible
& $py scripts\usim\annotate_episode.py --check `
  --annotations data\usim_enact\usim-enact-v0.1\annotations\episodes
# => checked 7, ok 7, key_frames 28, transitions 21, visible_transitions 21

# 2) spec 校验（不写文件）
& $py scripts\usim\annotate_episode.py --spec <spec.json> --check --dry-run

# 3) spec → 标注（工作副本）
& $py scripts\usim\annotate_episode.py --spec <spec.json> `
  --out data\usim_enact\_expansion\annotation_work\<annotator>\<episode> --check --verify-frames

# 4) 端到端编译验收（smoke 已跑通）
& $py scripts\usim\build_dataset.py `
  --annotations data\usim_enact\_expansion\smoke\annotations `
  --out data\usim_enact\_expansion\smoke\build --overwrite
# => [compiled] usim_train_episode_001304: 5 frames, 4/4 visible transitions
```

### 5.3 选片/取证复跑命令

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
# 选片（固定 seed；复跑哈希一致）
& $py scripts\usim\select_episodes.py
# 取证包（30 条；--overwrite 重建；--reindex 只重建 index.json）
& $py scripts\usim\build_episode_package.py --overwrite
& $py scripts\usim\build_episode_package.py --reindex
# 单条调试
& $py scripts\usim\build_episode_package.py --only 1304 --overwrite
```

### 5.4 `packages/index.json` 格式（稳定，供集成读取）

```json
{
  "schema_version": 2,
  "builder": "scripts/usim/build_episode_package.py",
  "selection": "...selection.jsonl",
  "package_count": 30,
  "counts_by_task": {...},
  "counts_by_block": {...},
  "counts_by_l5_route": {"touching": 23, "none": 1, "transfer_inbox": 6},
  "counts_by_l_max_baseline": {"3": 3, "4": 27},
  "counts_by_scene_hint": {...},
  "packages_supporting_l5": [6 transfer episode keys],
  "packages_touching_route_candidates": [...],
  "packages_with_warnings": [...],
  "sheets_missing": [],
  "packages": [ {episode_key, task_text, block_id, length, l5_route, l5_target_feasible,
                 l_max_states_baseline, l_max_states_optimistic, candidate_frames, sheets, ...} ]
}
```

注意：`l5_target_feasible` 在 index 中是**信号级**候选（transfer 6 条为 true）；task-10 视觉复核后已确认这 6 条的 InBox 不可证（§4.1），v0.2 build 时**不要**直接把它当 L=5 依据。

## 6. 对 v0.2 指南的建议（按优先级）

1. **不要默认用 transfer 支撑 L=5**：本批 transfer 全块 100/100 释放后不入箱、不沉降；`InBox` 在现有 ego 视频中不可证。建议 v0.2 QA 的 L=5 配额要么放弃，要么按 §4.4 路线 A 用 `NextTo(robot, green_box)`（需 Lead 在指南里写死语义/阈值/ego 判据），要么只对 touching 逐条复核后的少数 episode 开启。
2. **同步 `OnSeabed` 物理支撑语义到工具/包**：v0.2 规定“抓住但仍贴底 = true”；本次 package 的 `predicates_hypothesis` 仍沿用 v0.1 模板（grasp 帧给 OnSeabed=false），标注时以规范为准；若后续要自动生成 brief，需要把 hypothesis 改为物理支撑语义。
3. **选帧规则落到 dvl 高度**：`state[28]` 与物体离底高度一致（grasp 时约 0.20–0.25，离底上升时单调增大），建议 v0.2 指南把 key4 锚定为“dvl 上升起点 +40–60 帧”，并在 package v2 增加 `dvl_h` 曲线与 ascent onset；本批 package 已保存 dvl_h 的 summary，但未给 onset。
4. **渲染保持段**：USIM 每条 episode 只有 ~35–42 个唯一画面（8–14 帧重复）；v0.2 的“稳定帧”应显式记录 hold-run（连续相同帧区间），建议 annotator 在 notes 里写 `hold_run=[start,end]`；本包 stability 指标只是初筛。
5. **红色的“小鱼”干扰**：规范 §8.5 已确认红色游动物体是小鱼。任何按颜色自动给 object 的证据都要人工复核指代；建议 v0.2 标注 notes 固定写“目标指代依据 + 排除的干扰物”。
6. **L=4 为主、L=3 控制**：30 条中 27 条可做 L=4；建议 dev/val 的题集长度配额按 L=4 ≥ 2/3、L=3 ≤ 1/3、L=5 仅在有协议依据时另列。
7. **annotate_episode.py 统一流程**：所有 annotator 用 `--check --verify-frames` 后再交 Lead；`checks.json` 可直接由 `--check` 的 summary 输出落盘（task-10 已按此格式产出）。
8. **test_reserve 的 L=5 期望也要下调**：test_reserve 含 2 条 transfer（1378/1384），同样受“InBox 不可证”限制；冻结前建议用同一扫描脚本复核。
9. **题面排序捷径**：本批生命周期仍是单调的 4 状态，forward 题仍可能被文本先验部分解出；建议 v0.2 题面继续保留“动作文本去重/打乱”对照，并按 docs/06 条件 C 报告。

## 7. 风险与限制

1. **单标注者 + Lead 抽检**：本报告的“状态可辨/InBox 不成立”为 data-engineer 单人目视复核（6 条接触表 + 100 条 InBox 扫描），未做双人独立复核；v0.2 报告需如实写。
2. **包内 L=5 是信号级提案**：`transfer_inbox` 的 `available=true` 只表示“释放事件 + 沉降帧 + 箱可见”信号齐全，不等于视觉可证；task-10 的逐帧复核已否定。
3. **块边界是推断**：`Pick up the red cylinder` 的 200 条 run 在 100 条处拆成两块来自 CSV 子目录计数，meta 未声明；manifest 已标注 `block_split_inference`。
4. **场景 shallow/factory 未验证**：`scene.hint` 只基于亮度阈值，本批 29 条判为 bright_shallow_like、未出现 factory；与 587 的暗色结构背景矛盾，说明分类器不可靠，v0.2 不要用它做分层。
5. **同色歧义**：包内颜色检测是证据不是真值；287 已标记多分量歧义，红色小鱼可能造成误检；annotator 必须目视确认目标指代。
6. **稳定性 ≠ hold-run**：136/175 候选帧通过 ±10 帧 motion 检查，但不等价于 v0.2 的“渲染保持段内稳定帧”证据；annotator 需按规范复核。
7. **未修改 v0.1 / enact / 既有 scripts**：本次只新增文件；v0.1 目录只读未动。
8. **时间与版本**：本报告基于 2026-10-27 的 USIM 本地快照（manifest commit `88c3612b…`），后续若数据或 adapters 更新需重跑并记录差异。

## 8. 后续工作（task-10 起）

- 按 Lead 派发，data-engineer 标注批 E：`001304 / 001318 / 001330 / 001357`（transfer）。逐条输出 `annotation_spec.json` + `notes.md` + `checks.json` 到 `_expansion/annotation_work/data-engineer/<episode>/`。
- 关键前置结论（已复核）：这 4 条 **InBox 均不成立**，且没有 release_settle 证据 → 按规范退回 **4 帧（L≤4）**；1330 可能只有 3 个可辨状态（f80 前物体不可见），单独说明。若 Lead 批准 §4.4 路线 A（`NextTo(robot, green_box)`），可在 4 帧基础上加 at-box 第 5 帧再复核。
- 建议 Lead 尽快在 v0.2 指南中裁决：transfer 的 L=5 是否允许 at-box 路线；该决策影响 task-10 及后续 transfer 标注/QA 配额。

## 9. 追加：task-10 annotation batch E 结果（2026-10-27 晚）

Lead 已批准 at_box 路线（`NearBox(robot, green_box)`，v0.2 唯一 L=5 通道）并写入规范 §2.2/§3.1。
data-engineer 按新规范完成 transfer 批 E 四条标注，工作副本在
`data/usim_enact/_expansion/annotation_work/data-engineer/`：

| episode | key frames | L | at_box 帧证据 | InBox |
|---|---|---|---|---|
| 001304 | 132 / 177 / 244 / 292 / 481 | **L=5** | f481 = release−15，保持段 [480,491]，绿箱面积 4231（lift 帧 1500），物体仍 InGripper/Lifted；retry 型 close 192/229 | 不可证（释放 f496 距末 16 帧，红质心在箱 bbox 外） |
| 001318 | 200 / 245 / 275 / 352 / 517 | **L=5** | f517 = release−15，保持段 [510,523]，绿箱面积 2668（lift 1370），物体仍持有 | 不可证（释放 f532 距末 16） |
| 001330 | 80 / 107 / 154 / 344 | **L=4** | f344 = release−15，保持段 [342,353]，绿箱面积 4205；f80 前物体不可见 → 无合法 start 帧 | 不可证（释放 f359 距末 16）；退回则 L=3（3 帧） |
| 001357 | 133 / 178 / 208 / 286 / 445 | **L=5** | f445 = release−15，保持段 [432,451]，绿箱面积 2046；物体仍持有 | 不可证（释放 f460 距末 16） |

- 机械校验：`annotate_episode.py --check` 结果分别为 4/4、4/4、3/3、4/4 visible、0 empty；`build_dataset.py`
  编译全部通过（5/5/4/5 帧；4/4/3/4 可见转移）。
- 全 transfer 块 1300–1399 的 100 条扫描（`_expansion/probe/transfer_review/inbox_scan.json`）：
  `inside_box_last_frame = 0/100`，释放距末 16–18 帧，红目标质心位移 ≤60.7 px、无可见沉降 →
  **ego-only 无可靠 InBox 证据，v0.2 不启用 InBox**；transfer 的 L=5 仅由 at_box 提供。
- annotation 的 `notes` 字段已按要求补全（2767–2786 字符，覆盖 at_box/NearBox 定义、InBox 不可证、
  逐帧角色与 close/dvl/release 事件锚定、渲染保持段、green_box 可见性、ego 可判性 partial、
  红柱 vs 小鱼指代、L=5/1330 例外）；与 v0.2 已收副本 diff 仅 `notes` 字段。
- 风险：单标注者 + Lead 抽检；at_box/NearBox 的 ego 判定为 partial（定性，无距离阈值），报告须与
  标签值分列；1330 只能 L=4，不得为凑 L=5 补帧。
