# ENACT-USIM v0.2 协议证据（task-12）

日期：2026-10-27（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。数据集：`usim-enact-v0.2`（27 episode / 110 关键帧 / curated 120 题）。评分协议：`usim_strict_v0.3`。角色：protocol-engineer。
**状态：无需 API 密钥的 gate 全部完成并通过；A/B/C/D 模型条件待 `VLM_API_KEY` 真实运行。** 证据根（绝对路径，保持未跟踪）：`E:\code\UW-VLM\ENACT\data\usim_enact\_protocol\`。本文件是 task-12 的正式证据汇总；v0.1 侧方法与工具见 [评分契约与统计](ENACT-USIM-评分契约与统计-20261027.md)。

## 0. Gate 总表

| # | Gate | 结果 | 关键数字 | 证据 |
|---:|---|---|---|---|
| 1 | v0.2 QA 有效性（audit，v0.3 gate） | **PASS** | 120 题；**0 多答案**（接受集直方图 `{1:120}`）；**0 空/不可见参考转移**；参考排列 120/120 被接受；精确随机 EM/TA **0.3104**、PA_item **0.4431**、PA_micro **0.4185**；identity EM **0.2833**；与 Lead 侧 audit 逐项一致 | `data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.2.json` |
| 2 | 文本先验基线 v0.2（双模板） | **PASS** | 规则 `text_lifecycle_v2`；模板自检 14/14、合成排序自检 4/4；**inverse 60/60 文本可解**；forward 19/60；总体 EM **0.6583**、PA_item 0.7160、PA_micro 0.6955；identity 答案率 0.625 vs 参考 0.2833 | `data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.2.json` |
| 3 | 条件 D（forward 去动作文本） | **PASS** | 60 题（L3 27 / L4 30 / L5 3）；oracle **EM/TA/PA=1.0**（156 转移）；216 张图片全部存在；integrity 全过 | `data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/{enact_ordering.jsonl,build_manifest.json,oracle_report.json}` |
| 4 | v0.2 协议冻结 | **PASS** | 13 组 **1374 文件**；payload `d3370ad2…`；`--verify` exit 0（含 `--root E:\code\UW-VLM\ENACT`）；self-test 7/7；dataset 27 标注 + 220 帧哈希全对；test_reserve 10 条**只登记**、与 curated/splits/条件 D 零重叠；split seed 20261027（dev 84/19 ep、val 36/8 ep、test 未建）；规范/评测方案/条件 D/模型参数/评分 v0.3 全部入清单 | `data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027.json` + `.verify.json` |
| 5 | 程序基线 + dev/val 统计（report_stats） | **PASS** | all(120)：oracle 1.0 / identity 0.2833 / reverse 0.3750 / random 0.3333 / empty·malformed 0 / **text_prior 0.6583**（episode bootstrap CI [0.6140, 0.7037]）；dev(84)/val(36) 分层表已产出；empty/malformed 的 invalid 计数 = 该 scope 题数（固定分母生效） | `data/usim_enact/_protocol/stats/report_stats_v0.2_{all,dev,val}.json/.md` |
| 6 | A/B/C/D 模型条件 | **待运行** | 需要 `VLM_API_KEY`（环境变量，不落盘）；必须同一 `run_inference.py` 源码版本；运行后用 §7 命令出条件矩阵与 A−C/A−D/A−B 配对 | 尚无预测；§7 给出模板 |

## 1. v0.2 数据/题集事实（冻结文件确认）

| 项 | 值 |
|---|---|
| 数据版本 | `usim-enact-v0.2`（`manifest.json` sha 入冻结）；27 episodes（7 迁移 + 20 新增）、110 关键帧、83 转移 / 81 可见转移 |
| curated QA | 120 题，id 唯一；forward/inverse 各 60：L3 27、L4 30、L5 3；identity 参考率 **0.2833**；QA sha `f3cf687c…`（与 splits_manifest 记录的 qa_sha256 一致） |
| 原始 QA | 312 题（重排 seed 20261027）；curation manifest 记录 seed、配额、选择方法（选择规则在看模型成绩前固定） |
| splits | dev 84 题 / 19 ep，val 36 题 / 8 ep；`splits_manifest.json` seed **20261027**、test 在 `empty_splits`（冻结前不建）；dev+val id 集合 == curated id 集合 |
| test_reserve | 10 条候选 episode（`annotation_assignment.json`）：001078/001145/001259/001273/001378/001384/001497/001549/001650/001734；**未标注、未进入 curated QA / dev-val / 条件 D**，仅登记为 test 候选 |
| 模型配置 | 尚无 v0.2 run_config；冻结使用 `_protocol/v0.2_planned_model_config.json`（从 v0.1 冻结的 full_v1 配置派生，记录 `derived_from_sha256`；model/temperature/enable_thinking/max_completion_tokens 等与 v0.1 一致）。正式 run 必须复用此配置或以其为对照重新冻结 |

## 2. Gate 1：v0.2 QA 有效性（audit v0.3）

方法与 v0.1 相同：对每题枚举全部 `(L−1)!` 个排列（L=5 → 24 个），用真实 `USIMVerifier` 判定接受集；random 期望为精确枚举值。v0.3 `precheck` 强制参考转移可见签名非空，`evaluate` 从此不会对空签名题出分。

### 2.1 direction×L 汇总

| 设定 | N | 多答案题 | 随机 EM | 随机 TA | 随机 PA_item | 随机 PA_micro | identity EM | 空参考转移 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| forward L3 | 27 | 0 | 0.5000 | 0.5000 | 0.6296 | 0.6296 | 0.5185 | 0 |
| forward L4 | 30 | 0 | 0.1667 | 0.1667 | 0.3704 | 0.3704 | 0.1667 | 0 |
| forward L5 | 3 | 0 | 0.0417 | 0.0417 | 0.2708 | 0.2708 | 0.0000 | 0 |
| inverse L3 | 27 | 0 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0.3704 | 0 |
| inverse L4 | 30 | 0 | 0.1667 | 0.1667 | 0.3333 | 0.3333 | 0.1667 | 0 |
| inverse L5 | 3 | 0 | 0.0417 | 0.0417 | 0.2500 | 0.2500 | 0.0000 | 0 |
| **合计** | **120** | **0** | **0.3104** | **0.3104** | **0.4431** | **0.4185** | **0.2833** | **0** |

- 每题接受集直方图 `{"1": 120}`：**TA≡EM 在 v0.2 同样成立**（多答案路径仍由契约 fixture 覆盖，不依赖真实题集；报告须注明这一条件）。
- `gt_rejected_questions=0`、`empty_reference_transitions=0`：参考排列全部被自身 verifier 接受，v0.3 gate 在 v0.2 数据上通过。
- 与 Lead 侧 `_protocol/audit_qa_validity_usim-enact-v0.2.lead.json` 逐项一致：uniform EM/TA 0.3104、PA_item 0.4431、PA_micro 0.4185、identity 0.2833、直方图 `{1:120}`、0 空参考。**独立复现通过。**
- L=5 只有 3+3 题：单元 CI 很宽，只能作结构性诊断，不用于对外结论。

## 3. Gate 2：文本先验基线 v0.2（`text_lifecycle_v2`，双模板）

### 3.1 规则（脚本 `scripts/usim/text_prior_baseline.py`，sha `b5b098f2…`）

| 阶段 rank | 谓词 | 匹配模式 | 模板代际 |
|---:|---|---|---|
| 0 | OnSeabed | `on the seabed` | v0.1+v0.2 |
| 10 | NextTo | `next to` | v0.1 |
| 10 | NextTo | `in position for the (pre-grasp) approach beside` | v0.2 |
| 15 | Touching | `touching` | v0.1 |
| 15 | Touching | `in contact with` | v0.2 |
| 20 | InGripper | `grasped by the robot` | v0.1+v0.2 |
| 30 | Lifted | `lifted above the seabed` | v0.1+v0.2 |
| 35 | **NearBox** | `near`（v0.2 transfer at-box 状态） | v0.2 |
| 40 | InBox | `inside the (green) box` | v0.1+v0.2 |

- 生命周期顺序：`OnSeabed(0) < NextTo(10) < Touching(15) < InGripper(20) < Lifted(30) < NearBox(35) < InBox(40)`。Touching 在 approach 与 grasp 之间（v0.2 规范："接触但尚未持有"）；NearBox 在 Lifted 之后（transfer 的 at-box 释放位置）。
- 否定句守卫（`no longer` / `not … anymore` / `stopped being`）不贡献阶段。
- 只读 `question` 字段，不读 `gt_answer`/`images`/`key_frame_ids` 或任何模型输出。
- **向后兼容**：在 v0.1 上重跑，EM 仍为 0.7714 / PA_item 0.8024 / PA_micro 0.7987 / identity 0.7，与冻结 v0.1 证据逐位一致（`text_prior_baseline_usim-enact-v0.1.json`）。
- 自检：模板探针 **14/14**（覆盖 v0.1/v0.2 两代及否定句）、合成 inverse 排序探针 **4/4**（v0.1 生成、v0.2 生成、Touching 阶段、L=5 全链 NearBox）。证据记录 `template_compatibility` 与 `synthetic_order_probes`，失败时脚本非零退出。

### 3.2 v0.2 结果（真实 verifier 评分，120 题）

| 设定 | N | 文本基线 EM | TA | PA_item | PA_micro | identity 答案率 |
|---|---:|---:|---:|---:|---:|---:|
| forward L3 | 27 | 0.5185 | 0.5185 | 0.6296 | 0.6296 | 1.0 |
| forward L4 | 30 | 0.1667 | 0.1667 | 0.2889 | 0.2889 | 1.0 |
| forward L5 | 3 | 0.0000 | 0.0000 | 0.0833 | 0.0833 | 1.0 |
| inverse L3 | 27 | **1.0000** | 1.0000 | 1.0000 | 1.0000 | 0.3704 |
| inverse L4 | 30 | **1.0000** | 1.0000 | 1.0000 | 1.0000 | 0.1667 |
| inverse L5 | 3 | **1.0000** | 1.0000 | 1.0000 | 1.0000 | 0.0 |
| **合计** | **120** | **0.6583** | 0.6583 | 0.7160 | 0.6955 | 0.625 |

- **inverse 60/60 全部可被确定性文本规则解出（含 L=5）**：v0.2 的 inverse 仍然不能作为视觉世界建模能力证据；报告必须与 A/B/C/D 同表时标注"文本可解"。
- forward 文本基线 = 恒等标签先验（题目不给标签→动作映射），19/60 = 0.3167，与该组精确随机 EM 0.3104 几乎相同（两个方向的题量与长度分布相同，故 forward 随机期望 == 总体 0.3104）；forward 的 19 题命中主要来自 L3 的 identity 参考率（14/27），L4 只有 5/30、L5 为 0。
- overall 0.6583 低于 v0.1 的 0.7714，主因是 **curated 结构变化**：v0.2 L3 仅 45%（v0.1 80%），L4/L5 的机会与文本可解性都更低，不是文本规则变弱。
- 模板代际分布：102 题含 v0.2 专用模板标记（pre-grasp/in contact/near），18 题仅有共享模板（无法从文本判断代际，已记录 `undetermined_shared_template`）。
- 0 个 unresolved 标签；无模型去图条件 C 对照（v0.2 尚无 C 预测，`--condition-c-items` 未提供 → evidence 明确写 skipped）。

## 4. Gate 3：条件 D（v0.2，forward 去动作文本）

- 构造：只对 forward 题；删除 `## Actions in Order`（全部 `[Action N]`），preamble 由 "…result from applying a given series of actions…" 改为 "…follow a given initial state"；`## Your Task` 改为纯视觉"determine their chronological order using only the visual evidence; no action descriptions are provided"；`## Output Format`/示例/结尾请求逐字保留；`id/type/task_name/key_frame_ids/images/gt_answer/options` 不变。inverse 显式排除。
- 产物：`data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/`，60 题（L3 27 / L4 30 / L5 3），引用 **216** 张图片全部存在；QA sha `81d3382a0d8bd45a0236a2963aebc5fddf401500c9ff2efb51c7bc66d29271c7`；manifest payload `9082035d2ad5b701f065540d518e3ad88366509599ad3e2758c9efe14b8c5934`；question sha `f7265af5…`。
- oracle（v0.3 真实 verifier）：**EM=1.0 / TA=1.0 / PA_item=1.0 / PA_micro=1.0**（60 题、156 转移；L3/L4/L5 全 1.0）；integrity 全 true（仅 forward、id 与 curated forward 一致、非 question 字段逐条不变、无动作文本、输出格式保留）。
- 用途：A vs D 同 ID 配对 = forward 组"动作文本去掉后"的净影响；结合 §3 的 forward 文本先验（19/60）与 inverse 全文本可解，构成 v0.2 "视觉 vs 文本"的完整拆分。
- 限制：只有 forward（60 题）；L=5 仅 3 题；D 尚未跑模型；输出示例 `[1, 3, 2]` 从条件 A 逐字继承（v0.2 curated 中 gt 与示例相同的题数记录在 manifest `gt_equals_output_example`，供复核）。

## 5. Gate 4：v0.2 协议冻结

证据：`data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027.json`（362 KB）+ `.verify.json`。**13 组、1374 个文件**；`profile=v0.2`、`freeze_id=20261027`、`manifest_payload_sha256=d3370ad2b1b00ecd15b063e6b25d200418310cba6a9ae134d59669bc72339f8a`；`--verify` exit **0**（默认记录 root 与显式 `--root E:\code\UW-VLM\ENACT` 均通过）；`--self-test-v02` **7/7**（mock fixture：生成/校验/篡改检测、test_reserve 重叠检出、缺文档检出、条件 D id 不一致检出）。

> **重新冻结记录（发布前修正）**：首版冻结生成于 `2026-10-27T17:18:53+08:00`；随后 audit 证据在 `17:23:52` 被重跑（内容数字不变、`audited_at`/哈希变化），导致 Lead 独立 verify 时 `audit_evidence` 组出现 1 处 hash mismatch（payload 本身匹配）。已用**最终版** audit 证据重新生成冻结（`created_at=2026-10-27T17:25:34+08:00`，payload 如上），`--verify` exit 0、self-test 通过；**此后未再运行 audit/text-prior/条件 D/程序基线等任何会改写冻结证据的命令**（仅编辑本文件与评分契约报告，二者不在冻结组内）。

| 组 | 文件数 | 内容 | SHA-256 摘要 |
|---|---:|---|---|
| labels | 81 | 27 份 episode 标注 + 27 raw scene graph + 27 segmented scene graph | `a69268c6…` |
| images | 1240 | 27 ep 的 raw/segmented 帧与全部 QA 题面图（A 条件；B 条件目录当前为空） | `5e2ebfd7…` |
| qa | 4 | 原始 QA、curated QA、build summary、curation manifest | `a238d86f…` |
| docs | 2 | v0.2 标注与关键帧规范、v0.2 评测与正式测试方案 | `cbe72af2…` |
| registration | 1 | `annotation_assignment.json`（test_reserve 登记） | `528b1485…` |
| condition_d | 3 | 条件 D QA + build manifest + oracle report | `74a5b8cb…` |
| dataset_manifest | 1 | v0.2 `manifest.json` | `44b4e588…` |
| program_baselines | 12 | run 目录 `baselines/baseline_*.{json,items.jsonl}`（oracle/identity/reverse/random/empty/malformed） | `604fa7fb…` |
| inputs | 4 | `dev.jsonl`/`val.jsonl`/`dev_val.jsonl`/`splits_manifest.json` | `8fa1d952…` |
| model_config | 1 | 计划用模型配置（v0.1 冻结配置派生，no v0.2 run yet） | `a093c73c…` |
| audit_evidence | 1 | 本文件 §2 的 audit JSON | `87efcace…` |
| code | 24 | evaluate/run_inference/build_qa/build_dataset/migrate/curate/make_splits_v02/text_prior/adapters 等源码 | `f8a46c3b…` |
| run_artifacts | 0 | 尚无 A/B/C/D 模型 run（`inputs`/`baselines` 已入清单） | — |

关键硬校验（`generation_checks.all_hard_checks_pass=true`，失败项列表为空）：

- dataset manifest：**27 份标注哈希 + 220 个帧哈希全部匹配**（0 mismatch）；`migration_v01_to_v02.json` 入清单；
- curated QA：120 行、id 唯一、forward/inverse 均存在；curation manifest 的 `output_qa_sha256`/`total_selected`/seed 与 curated 文件一致；
- **test_reserve：10/10 登记，与 curated QA episode 0 重叠，未进入 dev/val split episode，未进入条件 D；`used_in_dev_val=false`**；
- splits：seed=20261027 且与请求一致；`dev∪val` id == curated id（120）；dev/val 不相交；**test split 不存在**（`empty_splits=["test"]`，无 test.jsonl）；
- 条件 D：id 集合 == curated forward id 集合（60），仅 forward，oracle 1.0；
- audit gate：存在、通过、0 空参考转移、0 参考被拒；multi-answer=0 记录在案；
- 规范/评测方案文档存在且入清单（sha：`ddbcc533…` / `3754c82f…`）；
- prompt/模型参数：格式指令 sha `987976c3…`（与 v0.1 相同），temperature=0、enable_thinking=false、max_completion_tokens=256、stream=false、timeout=180、attempts=3、DashScope URL；score=`usim_strict_v0.3`（evaluate.py sha `f18086e0…`，参考转移 gate enforced）；
- code snapshot：24 个源码 sha + git HEAD `e0d92e55…` + 40 条 dirty 记录；**A/B/C/D 正式 run 必须使用与此相同的 `run_inference.py` 源码版本**。

已知限制（入冻结清单）：新增 v0.2 标注为单标注者 + Lead 抽检（非双人独立）；ego-only 对距离/接触/离底存在 partial；test_reserve 冻结时未标注；本会话无 API key；qwen3.8-max 为别名模型；若真实 QA 多答案为 0 则 TA≡EM（本冻结确为 0）。此外：`model_config` 是**计划配置**而非真实 run 配置；正式 run 后应把 run_config/预测/报告作为新 run 冻结或重新生成清单。

## 6. Gate 5：程序基线与 dev/val 统计（report_stats）

为避免污染官方 run 目录，程序基线输出到 `_protocol/stats_v0.2/<scope>/<condition>/`（report.json + report.items.jsonl），再用 `report_stats` 汇总；所有条件使用同一 QA scope、v0.3 评分器、固定分母。**A/B/C/D 模型条件尚未产生**，因此本表仅含程序基线；模型列待 `VLM_API_KEY` 真实运行后按 §7 追加。

### 6.1 总体（all 120 题 / 27 episode；episode 分组 bootstrap 2000 次，seed 20261024）

| 条件 | N | EM | TA | PA_item | PA_micro | invalid/missing | EM 95% CI |
|---|---:|---:|---:|---:|---:|---:|---|
| oracle | 120 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 | [1.0000, 1.0000] |
| identity | 120 | 0.2833 | 0.2833 | 0.3826 | 0.3558 | 0 | [0.2154, 0.3615] |
| reverse | 120 | 0.3750 | 0.3750 | 0.5236 | 0.5032 | 0 | [0.2982, 0.4615] |
| random（seed=0） | 120 | 0.3333 | 0.3333 | 0.4889 | 0.4679 | 0 | [0.2622, 0.4167] |
| empty | 120 | 0 | 0 | 0 | 0 | 120（固定分母） | [0, 0] |
| malformed | 120 | 0 | 0 | 0 | 0 | 120（固定分母） | [0, 0] |
| **text_prior** | 120 | **0.6583** | 0.6583 | **0.7160** | **0.6955** | 0 | **[0.6140, 0.7037]** |

- 精确随机期望（枚举）：EM/TA **0.3104**、PA_item 0.4431、PA_micro 0.4185；identity 参考 0.2833。**text_prior 比精确随机高 +34.8pp、比 identity 高 +37.5pp、比 reverse 高 +28.3pp、比 random(seed0) 高 +32.5pp**。
- text_prior 的 EM 0.6583 全部来自 inverse（60/60）；forward 只有 19/60——因此 v0.2 的"文本捷径"读数集中在 inverse。

### 6.2 direction×L（text_prior / 机会水平）

| 设定 | N | 精确随机 EM | text_prior EM | text_prior PA_micro |
|---|---:|---:|---:|---:|
| forward L3 | 27 | 0.5000 | 0.5185 | 0.6296 |
| forward L4 | 30 | 0.1667 | 0.1667 | 0.2889 |
| forward L5 | 3 | 0.0417 | 0.0000 | 0.0833 |
| inverse L3 | 27 | 0.5000 | **1.0000** | 1.0000 |
| inverse L4 | 30 | 0.1667 | **1.0000** | 1.0000 |
| inverse L5 | 3 | 0.0417 | **1.0000** | 1.0000 |

### 6.3 dev / val 分层（episode 分组 bootstrap；详见 `_protocol/stats/report_stats_v0.2_dev.md` / `_val.md`）

| scope | N / episodes | oracle | identity | reverse | random | text_prior | text_prior EM CI |
|---|---|---|---:|---:|---:|---:|---:|---|
| all | 120 / 27 | 1.0000 | 0.2833 | 0.3750 | 0.3333 | **0.6583** | [0.6140, 0.7037] |
| dev | 84 / 19 | 1.0000 | 0.2857 | 0.4048 | 0.2976 | **0.6548** | [0.6023, 0.7031] |
| val | 36 / 8 | 1.0000 | 0.2778 | 0.3056 | 0.2500 | **0.6667** | [0.5938, 0.7692] |

- 固定分母验证：empty/malformed 在 dev/val 的 invalid 数分别 = 84 / 36，EM/PA 全 0；`oracle` 全 1.0 且 `reference_transition_gate` 记录 0 空转移。
- 配对（同 ID，episode 分组 bootstrap，all 120）：text_prior vs identity ΔEM **+0.3750 [+0.3148, +0.4272]**；vs random **+0.3250 [+0.2411, +0.4045]**；vs reverse **+0.2833 [+0.1667, +0.3897]**。所有配对计数/CI 在 JSON 中。

## 7. 待运行：A/B/C/D 模型条件（需要 `VLM_API_KEY`）

**当前明确标注：A/B/C/D 模型预测尚未产生，待 VLM_API_KEY/真实运行。** 运行要求：四条件使用**同一个 `run_inference.py` 源码版本**（冻结清单 code snapshot），同一 model/decode 参数，QA 分别为：

| 条件 | QA/输入 | 说明 |
|---|---|---|
| A 原图 | `_protocol` 中 curated QA（图像同 curated 记录） | 正式主条件 |
| B 局部放大 | 需先按 `build_crops.py` 规则生成 B 条件 QA/图 | 当前 v0.2 尚无 B 条件图（images 组中 B 目录为空） |
| C 去图 | curated QA + `--drop-images` | 文本先验模型对照 |
| D 去动作文本 | `_protocol/conditions/D_no_action_text_v0.2/enact_ordering.jsonl` | 纯视觉 forward 对照 |

运行目录模板（`$run` = `data/usim_enact/runs/qwen3.8-max/v02_dev_001`）：

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$v2 = 'data\usim_enact\usim-enact-v0.2'
$run = 'data\usim_enact\runs\qwen3.8-max\v02_dev_001'
# 需要会话内 $env:VLM_API_KEY（不落盘）
& $py scripts\usim\run_inference.py --backend openai --data-root $v2 `
    --qa "$v2\QA\train\enact_ordering_curated.jsonl" `
    --out "$run\A_full_image\predictions.jsonl" --max-completion-tokens 256 --sleep 1 `
    --condition-label A_full_image
& $py scripts\usim\evaluate.py --data-root $v2 --qa "$v2\QA\train\enact_ordering_curated.jsonl" `
    --predictions "$run\A_full_image\predictions.jsonl" --out "$run\A_full_image\report.json"
# B: build_crops 生成 B QA 后同法；C: 相同 QA + --drop-images；D: --qa 条件 D QA
```

模型预测齐备后：用 `report_stats` 把 A/B/C/D 与程序基线同表（同 ID 配对 A−C/A−D/A−B），并用 `_protocol/baselines_v0.2/text_prior_predictions.jsonl` 标注"文本可解/不可解"分层，分别报模型 EM（inverse 全文本可解层不能作为视觉证据）。**模型 run 完成后应重新冻结 run 产物（或用新 freeze_id）并保持 `--verify` 通过。**

## 8. 复跑命令（本轮全部已执行通过）

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$v2  = 'data\usim_enact\usim-enact-v0.2'
$run = 'data\usim_enact\runs\qwen3.8-max\v02_dev_001'
$P   = 'data\usim_enact\_protocol'

# 1) v0.2 QA 有效性（v0.3 gate）
& $py -m scripts.usim.audit_qa_validity --data-root $v2 `
    --qa "$v2\QA\train\enact_ordering_curated.jsonl" `
    --out "$P\audit_qa_validity_usim-enact-v0.2.json"

# 2) 文本先验基线（双模板；含 predictions-out 供 report_stats）
& $py -m scripts.usim.text_prior_baseline --data-root $v2 `
    --qa "$v2\QA\train\enact_ordering_curated.jsonl" `
    --predictions-out "$P\baselines_v0.2\text_prior_predictions.jsonl" `
    --out "$P\text_prior_baseline_usim-enact-v0.2.json"

# 3) 条件 D
& $py -m scripts.usim.build_condition_d --data-root $v2 `
    --qa "$v2\QA\train\enact_ordering_curated.jsonl" `
    --out-dir "$P\conditions\D_no_action_text_v0.2"

# 4) v0.2 协议冻结（含规范/评测方案/curated/图片/splits/条件 D/模型参数/评分 v0.3）
& $py -m scripts.usim.freeze_protocol --profile v0.2 --data-root $v2 `
    --run-dir $run --split-inputs-dir "$run\inputs" `
    --curated-qa "$v2\QA\train\enact_ordering_curated.jsonl" `
    --condition-d-qa "$P\conditions\D_no_action_text_v0.2\enact_ordering.jsonl" `
    --audit-evidence "$P\audit_qa_validity_usim-enact-v0.2.json" `
    --model-config "$P\v0.2_planned_model_config.json" --split-seed 20261027 `
    --freeze-id 20261027 --out "$P\freeze_usim-enact-v0.2_20261027.json" `
    --verify-out "$P\freeze_usim-enact-v0.2_20261027.verify.json"
& $py -m scripts.usim.freeze_protocol --verify "$P\freeze_usim-enact-v0.2_20261027.json"
& $py -m scripts.usim.freeze_protocol --self-test-v02

# 5) 程序基线（oracle/identity/reverse/random/empty/malformed + text_prior，all/dev/val 三个 scope）
#    每个 scope 用 evaluate.py 生成 report.json + report.items.jsonl，再跑 report_stats：
& $py -m scripts.usim.report_stats --run-dir "$P\stats_v0.2\all" --data-root $v2 `
    --condition oracle=oracle --condition identity=identity --condition reverse=reverse `
    --condition random=random --condition empty=empty --condition malformed=malformed `
    --condition text_prior=text_prior `
    --out-json "$P\stats\report_stats_v0.2_all.json" --out-md "$P\stats\report_stats_v0.2_all.md"
# dev / val 同法（--run-dir ...\dev、...\val；输出 *_dev/*_val）
```

程序基线重建说明：上述 §5 的 `_protocol/stats_v0.2/` 由一次性 driver 用 `evaluate.py --synthetic`（6 基线）与 `--predictions`（text_prior 预测过滤到各 scope）生成；命令与产物结构已在 `_protocol/stats_v0.2/program_baselines_manifest.json` 记录。若需完全重跑，按同一 CLI 逐 scope 生成即可（无需新脚本）。

## 9. 与 v0.1 的解读差异（写结果报告的硬要求）

1. **v0.2 的机会水平更低**：精确随机 EM/TA 0.3104（vs v0.1 0.4333），identity 0.2833（vs 0.4714）。L=5 的随机 EM 只有 1/24。模型分数必须与"精确随机 + identity + text_prior"三列并列读。
2. **TA≡EM 仍成立（多答案=0）**：v0.2 真实题集依然没有语义等价多解；TA 不是独立于 EM 的能力证据。契约 fixture（含多答案/不可交换/空签名）是评分路径的验证来源。
3. **inverse 仍是文本题**：v0.2 的 inverse 60/60 被确定性文本规则解出（含 L=5 NearBox 链）。A/B/C/D 报告必须把 inverse 标为"文本可解层"，视觉证据只能来自 forward（尤其 L4/L5）与条件 D。
4. **L=5 只有 3+3 题**：单元结论仅作结构诊断；不得用 L=5 单组数字做对外能力声明。
5. **A/B/C/D 必须同源码**：v0.1 的 P1（三条件三种 run_inference 版本）不得在 v0.2 重演；冻结清单的 `code_snapshot` 是唯一基准。
6. 对照条件 C 需要 v0.2 去图真实 run；目前没有，不得引用 v0.1 C 分数作 v0.2 对照。

## 10. 限制

- 新增 v0.2 标注是单标注者 + Lead 抽检，不是双人独立复核；10 条 test_reserve 仅登记、未标注。
- ego-only 320×240 对"距离/接触/离底/入箱"只有 partial 证据；B 条件（局部放大）当前 v0.2 尚未生成图，相关对照待建。
- 模型配置是**计划配置**（v0.1 冻结配置派生），不是 v0.2 真实 run 的 `run_config.json`；模型 run 后须以真实配置重新冻结 run 产物。
- 本会话无 `VLM_API_KEY`，A/B/C/D 未运行；`report_stats` 目前只含程序基线。
- qwen3.8-max 是别名模型，只能记录 request_id/响应 model/调用时间。
- `data/usim_enact/_protocol/` 被 `ENACT/.gitignore` 忽略、保持未跟踪（未 force-add、未改 ignore）；本文件用绝对路径引用证据。

## 附录 A：新增证据文件（相对 `E:\code\UW-VLM\ENACT\`）

| 文件 | 大小 | 内容 |
|---|---:|---|
| `data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.2.json` | 201 KB | 120 题逐题接受集/参考签名、direction×L×任务、精确机会水平、六基线回归 |
| `data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.2.json` | 104 KB | 逐题文本排序规则/阶段/证据、14+4 自检、EM/PA/identity、与机会对照、预测输出 hash |
| `data/usim_enact/_protocol/baselines_v0.2/text_prior_predictions.jsonl` | — | text_prior 的 120 条答案（供 report_stats/文本可解分层） |
| `data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/enact_ordering.jsonl` | 124 KB | 条件 D QA（60 题） |
| `data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/build_manifest.json` | 50 KB | D 变换规则/完整性/oracle/限制/payload |
| `data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/oracle_report.json` | 1 KB | D oracle（EM/TA/PA=1.0） |
| `data/usim_enact/_protocol/v0.2_planned_model_config.json` | 2 KB | 计划模型配置（v0.1 冻结配置派生 + 来源哈希） |
| `data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027.json` | 362 KB | v0.2 协议冻结（13 组 1374 文件 + 硬校验 + payload；refreeze 后 payload=`d3370ad2…`） |
| `data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027.verify.json` | 5 KB | 冻结即时校验（`ok=true`，payload 匹配） |
| `data/usim_enact/_protocol/templates/freeze_v0.2_template.json` | 9 KB | v0.2 冻结字段模板（section/required CLI/hard gates） |
| `data/usim_enact/_protocol/stats_v0.2/**` | — | 程序基线 report/items（all/dev/val × 7 条件）+ `program_baselines_manifest.json` |
| `data/usim_enact/_protocol/stats/report_stats_v0.2_{all,dev,val}.json/.md` | 6 文件 | direction×L×任务、episode bootstrap、配对 Δ、失败统计 |

环境：Windows + `C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe`；无外网调用。评分器 `evaluate.py` sha `f18086e0afcedc45229c3247ceb73cd70090017b133fce6ddf5a3c1165a86a6a`（v0.3，Lead 已冻结）；text_prior 脚本 sha `b5b098f2620aa5e0680a37671fba34ec573612d095fda5fe981a8d2e03a318f0`；split/curation seed 20261027，bootstrap seed 20261024。
