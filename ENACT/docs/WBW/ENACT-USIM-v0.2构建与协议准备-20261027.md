# ENACT × USIM v0.2 构建、协议升级与正式测试准备

执行日期：2026-10-27（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。
上游结果见 [qwen3.8-max 执行结果（v0.1）](ENACT-USIM-qwen3.8-max-执行结果-20261024.md)；本文件记录 v0.2 数据、题集、评分协议与正式测试准备的实际产物与证据。
**注意：v0.2 的 A/B/C/D 真实模型成绩尚未运行（会话无 `VLM_API_KEY`）；本文只发布构建、程序基线与协议冻结证据，不把开发集旧成绩写成 v0.2 成绩。**

## 摘要

| 项目 | 结果 |
|---|---|
| 数据版本 | `usim-enact-v0.2`：27 条 train episode（v0.1 迁移 7 + 新增 20），110 关键帧，83 个相邻转移（81 可见） |
| 独立复核 | v0.1 的 28 帧/21 转移完成第二方盲评（A 组 75.0%、B 组 73.4%）；修正 7 处 `OnSeabed`、2 处 visibility；`NextTo` 定义显式化；1302 入箱结论改判为“无可靠证据” |
| 题集 | 生成 312 题 → 重排（seed 20261027）→ 分层筛选 **120 题**：forward/inverse 各 L3 27 / L4 30 / **L5 3**；多选题=0、空参考转移=0、oracle 全对 |
| 机会水平 | exact uniform EM/TA **0.3104**、PA_item 0.4431、PA_micro 0.4185；identity 参考率 0.2833（v0.1 为 0.4333） |
| 程序基线 | oracle 1.0；identity 0.2833；reverse 0.375；random(seed 0) 0.3333；empty/malformed 0 |
| 评分协议 | `usim_strict_v0.3`：固定分母 + 严格解析 + **空/不可见参考转移 gate**；v0.1 A/B/C 回归逐位不变（0.9571/0.9286/0.7286） |
| L=5 | 仅 transfer 的 3 条（1304/1318/1357）通过 `at_box`/`NearBox(robot,green_box)` 支持 L=5（6 题）；transfer 100/100 条 `InBox` 不可证；pick 无 release_settle |
| 划分 | dev 19 条/84 题、val 8 条/36 题；test 预留 10 条（未标注，冻结后构建） |
| 冻结 | v0.2 协议冻结清单（见 `data/usim_enact/_protocol/`，hash 见 §8） |
| 未完成 | v0.2 的 A/B/C/D 模型运行、正式 test 构建与运行（均需 `VLM_API_KEY`） |

## 1. v0.2 数据与标注

### 1.1 组成

| 集合 | episode | 题数（curated） | 说明 |
|---|---:|---:|---|
| dev | 19（v0.1 7 + 新增 12） | 84 | 开发、prompt/参数选择 |
| val | 8（新增） | 36 | 选择与错误分析，不进入 test |
| test 预留 | 10（未标注） | — | `_expansion/annotation_assignment.json` 的 test_reserve；协议冻结后才构建 |
| 合计 | 27 标注 | 120 | |

- 新增 20 条按 v0.2 规范逐帧独立标注；每条约 4–5 帧：start → approach(NextTo) → grasp(InGripper，物理上仍贴底) → lift(Lifted) →（transfer）at_box(NearBox)。
- 任务覆盖：pick pipe 5、pick blue 5、pick red 3、transfer 4（1304/1318/1330/1357），另有 v0.1 迁移 7 条（blue 2、red 4、transfer 1）。
- L=5 支持：1304/1318/1357 三条 transfer（5 帧/4 可见转移）；1330 缺 start 帧 → L≤4；其余 pick 轨迹 L≤4（980 只有 3 帧/L=3）。

### 1.2 v0.1 → v0.2 迁移（只读原文件，生成新版本）

`scripts/usim/migrate_v01_to_v02.py` 生成 7 条迁移标注（`usim-enact-v0.2/annotations/episodes/`），逐条变化写入 `migration_v01_to_v02.json`：

- **`OnSeabed` 物理支撑语义修正 7 处**：抓住但仍贴底时 `OnSeabed=true`（v0.1 模板写成 false，无物理证据）；`OnSeabed=false` 只在 `Lifted` 可见时出现。
- **visibility 修正 2 处**：555/f140、556/f180 目标在 ego 中完全不可见却标 `visibility=true`；修正后这两条各失去 1 个可见转移（2/3），题集自动少生成相应路径。
- notes 修正（“red cylinder”实为游动小鱼）并写入 v0.2 语义说明。
- 迁移后 7 条仍为 3/3 或 2/3 可见转移；QA 会由构建流程重新生成，v0.1 问卷不再复用。

### 1.3 语义与动作文本变更

- `NextTo` 显式定义为 **approach**（抓取前 15±5 帧的到位窗口；抓住后恒 false，不是纯几何距离）。
- `OnSeabed` 用物理支撑语义（§1.2）。
- 新增 `NearBox(robot,green_box)`：transfer 的 at_box 释放位置（不得替代 `InBox`）。
- 动作文本模板：`NextTo` → “in position for the pre-grasp approach beside”，`Touching` → “in contact with”，消除 “grasped … no longer next to” 的自然语义矛盾；相应文本先验基线同时兼容 v0.1 模板。
- 规范：`docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md`（含复核裁决 §8、事件锚定 §3.0、L=5 路线 §3.1）。

## 2. 独立标签复核（round 2）

产物：`data/usim_enact/_review/round2/reviewer_a/`、`.../reviewer_b/`（pass1 盲评写盘+哈希锁 → pass2 对照 → pass3 视频/信号裁决）。

| 组 | 帧×关系 | 精确一致 | 剔除 undecidable | 关键结论 |
|---|---:|---:|---:|---|
| A（200/201/552） | 48 | 75.0% | 81.8% | 硬分歧 8 处全为 `NextTo` 定义问题；`OnSeabed` 3 处无物理证据 |
| B（553/555/556/1302） | 64 | 73.4% | 82.5% | `InGripper` 16/16、`Lifted` 14/16；2 处 visibility 明确错误；1302 无入箱证据 |

- 7 条 v0.1 episode 的 4×4 事实表完全同构（模板），证实“21 转移均可见”是模板推论而非逐帧判断。
- `NextTo` 8+12 处分歧全部归因于定义（approach vs 几何距离）；A 组 key2 全部 = close−15，事件锚定下 v0.1 值自洽但文档未定义。
- **`OnSeabed` 修正**：7 条 key3 的 dvl 离底高度均为局部最低、上浮起点在其后 22–47 帧；wrist 显示抓住后无竖直位移 → 物理支撑语义下应为 true。
- **qwen3.8-max v0.1 的 3 处错误全部落在 ep000200**，且正是复核认定最弱的两类转移（NextTo/抓取阶段、Lifted 可见性）→ v0.1 的 0.9571 残差不能直接归因模型能力。
- 第二标注者交叉复核（reviewer-a 盲评 reviewer-b 的 501/587）：**32/32 逐帧逐谓词一致、0 分歧**（样本 2 条，非全量）；两份标注 L 路线与排除理由一致。
- **限制（如实报告）**：v0.2 新增标注为 1 名标注者 + Lead 抽检；双人一致率仅 2 条抽样证据；“ego 可判性”在距离/接触/离底上多为 partial，辅助信号仅作旁证。

## 3. 题集构建与门禁

流程（命令见 §9）：`build_dataset` → `build_qa --step-lengths 3,4,5` → `reseed_answers --seed 20261027` → `curate_qa_v02 --quotas 5:2,4:3,3:1` → `audit_qa_validity` gate。

| 设定 | 题数 | exact uniform EM/TA | identity 参考率 | 备注 |
|---|---:|---:|---:|---|
| forward L=3 | 27 | 0.5000 | 0.5185 | 与 ENACT/v0.1 兼容，分辨力低 |
| forward L=4 | 30 | 0.1667 | 0.1667 | 主要视觉指标 |
| forward L=5 | 3 | 0.0417 | 0.0000 | at_box（3 条 transfer） |
| inverse L=3 | 27 | 0.5000 | 0.3704 | 文本先验主导（见 §6） |
| inverse L=4 | 30 | 0.1667 | 0.1667 | — |
| inverse L=5 | 3 | 0.0417 | 0.0000 | — |
| **合计** | **120** | **0.3104** | **0.2833** | PA_item 0.4431 / PA_micro 0.4185 |

门禁结果（`data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.2.lead.json` + protocol-engineer 正式版）：

- 多选题 **0**（接受集直方图 {1:120}）→ 该题集 TA≡EM；多答案路径由合成契约样例覆盖（`check_scoring_contract_v2.py`）。
- 空参考转移 **0**、参考排列全部被 verifier 接受、gt 拒绝 0。
- oracle（v0.3 precheck 下）EM/TA/PA **全 1.0**，120 题 / 312 转移。
- 程序基线：identity 0.2833、reverse 0.375、random(seed 0) 0.3333、empty/malformed 0（`runs/qwen3.8-max/v02_dev_001/baselines/`）。

**说明**：v0.2 的 L=3 仍占 54/120，但每 episode 每题方向只保留 1 条；主指标应报告 L≥4（66/120）与 L=5，L=3 单独给以兼容 ENACT 对照。

## 4. L=5 结论与 transfer 负结果

- **transfer `InBox` 不可证**：1300–1399 全部 100 条 transfer 的释放均发生在视频结束前 16–18 帧；释放后目标质心 100/100 不在绿箱 bbox 内、无沉降帧 → v0.2 不标注 `InBox`。
- **pick `release_settle` 不可用**：选中样本结束时仍持有物体，无最终 open 事件。
- **`touching` 不可用**：close 落在渲染保持段内部，close 前后只有“夹爪张开在物体上方”与“已夹住并随夹爪”两个唯一画面，不存在稳定“已接触未抓住”的 ego 帧。
- **唯一 L=5 通道 = at_box**：`NearBox(robot,green_box)` 作为第 5 状态；独立抽查 4/4 成立（1304/1318/1357 支持 L=5，1330 缺 start 只能 L≤4），且**无 InBox 误标**。证据：`_expansion/annotation_work/reviewer-a/crosscheck/transfer_at_box_check.{json,md}`、`_expansion/probe/transfer_review/inbox_scan.json`。
- 因此 v0.2 的 L=5 只有 6 题（forward 3 / inverse 3）；报告须写明“L=5 只覆盖 transfer at_box，不代表通用长时域能力”。

## 5. 评分协议 `usim_strict_v0.3` 与契约

在 v0.2 基础上（固定分母、严格解析、缺资产即失败、重复/未知 ID 拒绝）新增：

- **空/不可见参考转移 gate**：precheck 对每题每个参考转移计算可见签名；任一为空 → `AssetError`、CLI 退出 2、不发布报告。报告新增 `reference_transition_gate` 段。
- **v0.1 回归**：A/B/C 在 v0.3 下 EM/TA/PA 与 v0.2 存档逐位一致（0.9571 / 0.9286 / 0.7286），旧 report/items/predictions 哈希不变 → gate 不影响已发布数字。
- **空签名拒绝**：合成 diff 空/可见性过滤后空 + 真实数据端到端（相邻重复帧）均被 precheck 拒绝；上游 verifier 仍会对空签名给虚假 TA=1，故此 gate 是必要的。
- **多合法顺序契约**（a–f 全过）：≥2 语义合法顺序都 TA=1 且 EM 只认参考；不可交换动作交换后 TA=0；空签名拒绝；固定分母边界 `PA_micro=0.4`；严格解析；重复/未知 ID 拒绝。
- 证据：`data/usim_enact/_protocol/contract/check_scoring_contract_v2.json`、`_protocol/contract/regression_v0.1/`；脚本：`check_scoring_contract_v2.py`。

## 6. 文本先验与统计口径

### 6.1 v0.1（已发布）

程序化文本基线（只读题面动作文本、不看图）总体 EM **0.7714**，高于模型去图条件 C 的 **0.7286**；inverse 文本基线 **35/35**。

- 因此 v0.1 的 “A−C = +0.229” 应改写为“原图相对确定性文本基线 +0.186”；inverse 不能作为视觉能力证据。
- 统计口径（episode 分组 bootstrap，2000 次，seed 20261024）：A 0.9571 [0.8714,1.0]、B 0.9286 [0.8143,1.0]、C 0.7286 [0.6714,0.8]；A−C +0.2285 [+0.1285,+0.3143]；A−B +0.0285 [0,+0.0572]（不可区分）。
- 证据：`_protocol/text_prior_baseline_usim-enact-v0.1.json`、`_protocol/stats/`。

### 6.2 v0.2（本次，`text_prior_baseline_usim-enact-v0.2.json`）

脚本同时兼容 v0.1/v0.2 模板（新增 NearBox，rank 35；Touching 15），在 120 题 curated QA 上：

| 设定 | 文本先验 EM | 说明 |
|---|---:|---|
| forward 全部 | 0.3167 | 与 exact uniform 0.3104 基本持平；文本给不出 action→future-image 标签映射 |
| forward L3 / L4 / L5 | 0.5185 / 0.1667 / 0.0000 | 分别为各设定机会水平（identity 先验） |
| inverse 全部 | **1.0000 (60/60)** | **v0.2 的 inverse 仍可被纯文本基线完全解出** |
| **总体** | **0.6583** | PA_item 0.7160、PA_micro 0.6955、identity 答案率 0.625 |

**结论（必须写进任何 v0.2 模型报告）**：即使加入 at_box/NearBox 与新措辞，inverse 仍是文本先验题；v0.2 的视觉能力证据只能来自 **forward L≥4**、条件 D（去动作文本）与文本可解分层，而不是 inverse 高分。

### 6.3 v0.2 程序基线与分组统计（`_protocol/stats/report_stats_v0.2_{all,dev,val}.{json,md}`）

| 条件 | N | 有效排列 | invalid/missing | EM | TA | PA_item | PA_micro |
|---|---:|---:|---:|---:|---:|---:|---:|
| oracle | 120 | 120 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| identity | 120 | 120 | 0 | 0.2833 | 0.2833 | 0.3826 | 0.3558 |
| reverse | 120 | 120 | 0 | 0.3750 | 0.3750 | 0.5236 | 0.5032 |
| random(seed 0) | 120 | 120 | 0 | 0.3333 | 0.3333 | 0.4889 | 0.4679 |
| empty / malformed | 120 | 0 | 120 | 0 | 0 | 0 | 0 |
| text_prior | 120 | 120 | 0 | 0.6583 | 0.6583 | 0.7160 | 0.6955 |

- episode 分组 bootstrap（2000 次，seed 20261024）与 direction×L、任务、episode 三层表已生成（all/dev/val 三份）；text_prior 的 episode bootstrap CI 为 **[0.6140, 0.7037]**（dev 0.6548 / val 0.6667）；单个 episode 的分位等于点估计（重采样单位即 episode），不确定性看总体/direction×L 层。
- 逐 setting：forward L3 的 identity 0.5185、L4 0.1667、L5 0；inverse L3 的文本先验 1.0。程序基线是**模型报告必须并列**的对照，尤其 identity（固定顺序捷径）与 text_prior（文本捷径）。
- v0.2 的 B 条件（局部放大）尚未生成（v0.1 的 B 为负结果、天花板限制），属可选对照；条件 C/D 的 v0.2 QA 由 protocol-engineer 构建，待模型运行后与 A 配对报告。

## 7. 条件矩阵与运行准备（A/B/C/D）

| 条件 | 输入 | 状态 |
|---|---|---|
| A 原图 | ego 全图 | dry-run 通过（v0.2 dev 84 题/19 ep；format directive sha 与 v0.1 冻结一致 `987976c3…`） |
| B 局部放大 | `[原图 \| 局部]` | 脚本存在（`build_crops.py`，v0.1 用过）；v0.2 尚未生成，属可选对照 |
| C 去图 | 仅题干 | dry-run 通过（`--drop-images`） |
| D 去动作文本 | forward 题干删除动作列表 | v0.1 35 题/oracle 1.0；**v0.2 60 题（fwd L3 27/L4 30/L5 3）、oracle 1.0、216 图全在**（`_protocol/conditions/D_no_action_text_v0.2/`，QA sha `81d3382a…`） |
| 程序基线 | oracle/identity/reverse/random/text-prior | v0.2 已跑（§3）；text-prior v0.2 见 §6 |

运行准备证据：

- `runs/qwen3.8-max/v02_dev_001/inputs/{dev,val}.jsonl` + `splits_manifest.json`（dev 84 题/19 ep、val 36 题/8 ep）。
- A/C/D 的 `--dry-run` 均通过（dummy key 仅用于输入校验，未发请求）；`run_config.json` 记录 URL/模型/思考/解码/格式指令/QA 与图片哈希，不存密钥。
- **P1（v0.1 遗留）**：v0.1 的 A/B/C 三次 run 使用 3 个不同 `run_inference.py` 版本；v0.2 的 A/B/C/D 必须在同一源码版本上运行并在冻结清单记录源码哈希。
- 正式测试需要 `VLM_API_KEY`（仅环境变量）；当前会话没有，故 v0.2 只做到构建/基线/协议冻结与 dry-run。

## 8. 协议冻结与正式 test 计划

**冻结已完成**（`data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027.json`）：

- 13 组 **1374 文件**（labels / images / QA / run inputs / baseline / splits / condition D / model config / docs / code 等），payload `35568227a73ee011b217f8a7f13922fe78f830a385c39d117f255252232eb85e`；
- **48 项硬校验全过**，`--verify` exit 0，`--self-test-v02` 7/7；dataset 27 标注 + 220 帧哈希全对；
- 规范 sha `ddbcc533…`、评测方案 sha `3754c82f…`；splits seed 20261027（dev 84/19ep、val 36/8ep、test 未建）；
- **test_reserve 10 条仅登记**：与 curated QA / splits / 条件 D **零重叠**、`used_in_dev_val=false`；
- `model_config` 是**计划配置**（v0.1 冻结配置派生）；A/B/C/D 运行后须以真实 `run_config` 重新生成/补充冻结（新 freeze_id），并保持 `--verify` 通过。

**正式 test**（冻结后执行，不参与任何选择）：

1. 用冻结规则标注 test_reserve 的 10 条（标注者不看任何 test 模型输出）。
2. 用同一构建/筛选/重排流程生成 test QA；`audit_qa_validity` + oracle + v0.3 gate 必须通过；QA 哈希写入冻结清单。
3. A/B/C/D + 程序基线各运行一次（同一模型、同一 `run_inference.py` 源码版本）；只报告一次，不得据 test 调整 prompt/参数/配额。
4. 报告按 direction×L×task、episode 分组 bootstrap CI、A−C/A−D 配对差值、失败/格式错误/缺失计数；标签若发现错误 → 升版本（v0.2.1）并全条件重评。
5. 目前 test 构建与运行待 `VLM_API_KEY`；test 候选与划分规则已固定（`annotation_assignment.json`），冻结清单已登记。

## 9. 复现命令

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py  = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$v2  = 'data\usim_enact\usim-enact-v0.2'
$run = 'data\usim_enact\runs\qwen3.8-max\v02_dev_001'

# 迁移 + 构建 + 题集 + 重排 + 筛选
& $py scripts\usim\migrate_v01_to_v02.py --annotations data\usim_enact\usim-enact-v0.1\annotations\episodes --out "$v2\annotations\episodes"
& $py scripts\usim\collect_v02_annotations.py --overwrite   # 20 条新增标注校验入集
& $py scripts\usim\build_dataset.py --annotations "$v2\annotations\episodes" --out $v2 --overwrite
& $py scripts\usim\build_qa.py --data-root $v2 --step-lengths 3,4,5 --num-to-sample 25
& $py scripts\usim\reseed_answers.py --data-root $v2 --qa "$v2\QA\train\enact_ordering.jsonl" --seed 20261027
& $py scripts\usim\curate_qa_v02.py --data-root $v2 --qa "$v2\QA\train\enact_ordering.jsonl" --out "$v2\QA\train\enact_ordering_curated.jsonl"

# 门禁 + 基线 + 划分
& $py scripts\usim\audit_qa_validity.py --data-root $v2 --qa "$v2\QA\train\enact_ordering_curated.jsonl" --out data\usim_enact\_protocol\audit_qa_validity_usim-enact-v0.2.json
& $py scripts\usim\evaluate.py --data-root $v2 --qa "$v2\QA\train\enact_ordering_curated.jsonl" --synthetic oracle --out "$run\baselines\baseline_oracle.json"
& $py scripts\usim\make_splits_v02.py --qa "$v2\QA\train\enact_ordering_curated.jsonl" --out-dir "$run\inputs"

# 运行准备（dummy key 仅用于 dry-run 输入校验，不会发请求）
$env:VLM_API_KEY='dry-run-placeholder'; $env:VLM_API_URL='https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'; $env:VLM_MODEL_NAME='qwen3.8-max'
& $py scripts\usim\run_inference.py --data-root $v2 --qa "$run\inputs\dev.jsonl" --out "$run\A\predictions.jsonl" --api-url $env:VLM_API_URL --model $env:VLM_MODEL_NAME --enable-thinking false --max-completion-tokens 256 --condition-label A_ego_full --dry-run
```

## 10. 限制

1. v0.2 没有真实模型成绩；本文所有 EM 均为程序基线/机会水平，不能写成模型能力。
2. 新增标注为单标注者 + Lead 抽检；2 条双人交叉复核 100% 一致，但不足以替代全量标注者间一致性。
3. L=5 仅 6 题（transfer at_box）；`InBox`、`release_settle`、`touching` 均无 ego-only 证据，不能宣称长时域或入箱能力。
4. `ego 可判性` 对距离/接触/离底多为 partial；导出的标签值正确不等于模型能从单张 ego 图判定。
5. v0.1 的 A/B/C 用 3 个不同 runner 版本（P1）；v0.2 必须同版本重跑，旧对照只能表述“无可测增益”。
6. 文本先验问题未消失：v0.2 的 inverse 仍需附程序文本基线与去图条件，主视觉指标用 forward L≥4 与条件 D。
7. `qwen3.8-max` 为别名模型，底层快照可能变化；只能记录调用时间、request_id 与响应 model。

## 11. 材料索引

| 文件/目录 | 作用 |
|---|---|
| `docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md` | v0.2 标注、语义、选帧、L=5 路线、复核裁决 |
| `docs/WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md` | 条件矩阵、指标、冻结与 formal test 方案 |
| `docs/WBW/ENACT-USIM-评分契约与统计-20261027.md` | v0.3 gate、多答案契约、文本先验、v0.1 统计与冻结 |
| `docs/WBW/ENACT-USIM-v0.2协议证据-20261027.md` | v0.2 audit/text-prior/D/freeze/stats 五 gate 证据与命令 |
| `docs/WBW/ENACT-USIM-扩展候选与工具-20261027.md` | 30 条候选、取证包、L=5 负结果、at_box 证据 |
| `data/usim_enact/_review/round2/reviewer_a|b/` | 独立盲评、裁决、双人交叉复核、at_box 抽查 |
| `data/usim_enact/_expansion/` | 候选选择、取证包、标注工作副本、assignment/migration |
| `data/usim_enact/usim-enact-v0.2/` | v0.2 数据、manifest、QA、migration_v01_to_v02.json |
| `data/usim_enact/runs/qwen3.8-max/v02_dev_001/` | dev/val 输入、程序基线、dry-run run 目录 |
| `data/usim_enact/_protocol/` | audit/contract/text-prior/D/freeze 证据（本机可读，gitignore 未入库） |
