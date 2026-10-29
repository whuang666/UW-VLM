# 下一步工作清单与运行手册

验收页v2已完成[试填→导出→导入→下游校验闭环](../../docs/workbuddyRead/acceptance_ui_interaction_20261029_zh.md)，并修复v1异常导入覆盖进度的问题。请使用v2工作包；真实独立裁决仍0/10，后续还需根据裁决重建候选、重算程序门禁和最终冻结。

最新验收入口：[可执行工作包](../../docs/workbuddyRead/test_human_acceptance_workpack_20261029_zh.md)，含离线填写页、每条4项判断、判否处置及签字后的版本化／冻结流程。当前0/10；1650若排除需重建9条18题的新版本、重新均衡和重算基线，不能直接沿用旧20题门禁。图片策略已收紧为忽略新的数据集PNG，保留文字与重建证据；历史跟踪图片不移除。

最新构建进度（2026-10-29）：[均衡QA候选v1](../../docs/workbuddyRead/test_reserve_balanced_qa_build_20261029_zh.md)已按20行既定映射落地，图像／题面／答案与输入快照可复核；程序门禁通过。下一步裁决1650@f0的目标可见性、完成独立验收，再准备条件派生与最终执行冻结。文本基线inverse10/10，不能把该方向高分当视觉证据；此前“尚未重建”的段落为前序快照。

最近更新：2026-10-29（Asia/Shanghai）。**588次双协议开发对照与P4统计已完成；test采用独立的保守候选批次，8条L3、2条L4，Lifted不进入该候选scope。完整链20道诊断题的唯一性与oracle门禁通过；独立人眼验收仍0/10。下一步确定正式QA打乱策略、构建并全量复核实际输入，再做文本基线和独立质量验收；尚无val／test模型成绩。** [本轮审计与证据](../../docs/workbuddyRead/test_reserve_conservative_semantic_20261029_zh.md)，[保守候选](WBW/evidence/test_reserve_conservative_20261029/README.md)，[完整开发指标](WBW/ENACT-USIM-双协议2048开发对照结果-20261028.md)。20道诊断题有固定seed答案偏置，不直接作为正式test；下列带早期日期的条目保留历史范围。

这份清单按依赖排序。**GPU 训练仍不在当前阶段。** 数据集已经确定为当前工作区的 USIM（`E:\code\UW-VLM\usim`）。

排列策略已有[可审阅方案与20行映射预览](../../docs/workbuddyRead/test_reserve_permutation_strategy_20261029_zh.md)：全部排列（含恒等）按方向×长度均衡，实际verifier枚举继续作为唯一性门禁。L4每方向仅2题，最佳常量下限0.5，不宣称降至1/6。下一项按该版本实现独立QA／图片重建及频数、图文绑定、oracle等门禁；当前没有重写正式输入。

2026-10-29 dev只读试跑已完成：[规则可操作性结果与逐条入口](../../docs/workbuddyRead/dev_lift_onset_feasibility_20261029_zh.md)。19条／84题、38份源文件哈希与时间对齐通过；16条有视觉细核入口，未确认首个合格半宽离底状态。另发现533／1302旧帧距及553起始稳定性问题。下一步继续在dev补齐A/B证据与间隙参照，暂不将草案升级为正式test协议；0次API调用，历史数据和test标注保留。

后续[501单条样板链](../../docs/workbuddyRead/dev_lift_chain_ep000501_20261029_zh.md)已定位失败：目标轮廓能量取，局部地面参照及物理离底时间仍不可确认。下一步补可复查的接触／地面参照或已核验几何，先取得阳性样板再扩展；1302的18帧违反旧20帧下限，单列既有标注修订，不能仅归于草案更严。

## P0：先使数据与协议可信（2026-10-27 状态）

| 状态 | 工作 | 交付物与验收标准 | 证据 |
|---|---|---|---|
| ✅ 已完成 | 阅读论文、代码和数据结构 | 本套文档、来源索引、合成契约检查 | [01](01_paper_reading.md)、[02](02_code_and_reproduction.md) |
| ✅ 已完成 | 已到位 test Parquet 核验 | 525 文件、208,605 行可读，结构检查通过（不代表视频或标签齐全） | [03 数据核验 §1–§2](03_usim_data_audit.md) |
| ✅ 已完成 | 补齐 USIM 下载 | 固定远端 commit、分页全清单 6,840 个文件（4,219,493,970 字节），逐文件内容哈希核验全部通过；train 1,750 Parquet / 3,500 视频，test 525 / 1,050 | [03 顶部更新](03_usim_data_audit.md) |
| ⚠️ 部分完成 | 建立隔离环境 | 实际运行统一使用 `C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe`（numpy/pyarrow/opencv 可用）；原计划的独立 conda 环境与依赖锁**未建**，环境版本未锁定（待核实） | [07 §8](07_reproduction_run.md)、[评分契约 §8](WBW/ENACT-USIM-评分契约与统计-20261027.md) |
| ⚠️ 部分完成 | 确认动作与坐标语义 | 夹爪 `observation.state[0]`、离底高度 `state[28]` 已作为**辅助证据**用于复核；完整关节/推进器映射、单位与 `target_pos` 语义仍待上游源码确认 | [03 §3–§4](03_usim_data_audit.md)、[round2 B §1](<../data/usim_enact/_review/round2/reviewer_b/review_report.md>) |
| ✅ 已完成 | 确定首版标签与标注来源 | v0.1：4 谓词、`agent_visual_review`、70 题；v0.2：`OnSeabed` 物理支撑语义、`NextTo` approach 语义、可见性与选帧规则已写入规范 | [v0.2 标注与关键帧规范](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md) |
| ✅ 已完成 | 从 train 划开发/验证集合 | v0.1：7 条 train episode 作开发集，seed 20261024；v0.2：按 episode 划分，dev 19 / val 8 / test 预留 10（test 冻结后才标注） | [07 §2](07_reproduction_run.md)、[v0.2 评测方案 §2](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md) |
| ✅ 已完成 | 评分修复（P0 遗留） | 固定分母、严格解析、资产预检失败即退出；`usim_strict_v0.3` 新增“参考转移可见签名为空”gate；6 项契约测试全过、v0.1 回归逐位一致 | [契约证据](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)、[评分契约 §3/§10](WBW/ENACT-USIM-评分契约与统计-20261027.md) |
| ✅ 已完成 | 真实模型推理 | `qwen3.8-max` 70 题开发集 A/B/C 三条件，70/70 请求成功、格式全合法 | [执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md) |

数据下载验收以元数据和冻结 manifest 为准，数量相同仍需检查路径、大小、哈希、解码和时间对应。`tools/hf_snapshot_download.py` 的递归 API 分页问题已修复；6,840 个文件的逐文件哈希证据见 03 顶部链接。旧文档“尚待补齐下载”已过时。

## P1：做一个能人工检查的小闭环（2026-10-27 状态）

| 顺序 | 工作 | 验收条件 | 状态与证据 |
|---:|---|---|---|
| 1 | 从 train 挑 10–20 条操作轨迹 | 原视频、Parquet、指令/场景来源可追溯；不是从 test 挑“容易题” | ✅ v0.1 已用 7 条；v0.2 新增 20 条（dev 12 / val 8）已登记、标注进行中（[v0.2 评测方案 §2](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md)） |
| 2 | 人工标注关键帧、关系和可见性 | 至少 2–4 种可靠变化；记录未知和分歧，独立复核覆盖每种谓词 | ✅ v0.1 28 帧已复核（round2 盲评 + 裁决），v0.2 定义与选帧规则已写入规范 v1（[规范](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)） |
| 3 | 写 USIM reader 与标签适配层 | 帧 0 与 frame_index=0 对齐；ego 映射、episode 主键、标签来源正确 | ✅ 已在 07 §1 落地（[07 §1](07_reproduction_run.md)） |
| 4 | 编译稀疏场景图与分帧输入 | unknown 不被误当 false；没有虚构 visibility 像素数；不强行运行稠密分帧 | ✅ v0.1 已编译并通过 oracle；v0.2 要求逐帧独立标注（[07 §4](07_reproduction_run.md)） |
| 5 | 生成 `L=3/4` 双向题 | 目标约 100–200 QA，达不到时报告实际数；每个转移可在输入图验证 | ✅ v0.1 70 题（56×L3 + 14×L4）；v0.2 目标准备 L=4/5（[07 §5](07_reproduction_run.md)） |
| 6 | 验证题集与 scorer | 所有参考答案通过；非法排列拒绝；EM/TA 区分，多答案行为有审查记录 | ✅ oracle 1.0；多答案题 = 0 → TA≡EM（已审计），多答案路径由合成契约覆盖（[审计](../data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.1.json)） |
| 7 | 写一个模型推理器 | 模型实际收到全部图、正确标签和题干；不收到答案/帧号/时间信息 | ✅ `run_inference.py`（多图鉴权、dry-run、断点续跑、配置哈希）；70/70 成功（[执行结果 §2](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)） |
| 8 | 开发集运行 20–50 题 | 预测逐行保存；失败计入；中断能续跑 | ✅ 超额完成：70 题 A/B/C 三条件（[执行结果 §5–§7](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)） |

如果第 2–5 步发现大量语义变化不可见或不足以形成短题，先调整数据范围/标签设计；不要直接扩模型数量或开始微调。round2 复核已确认 v0.1 部分转移 `ego-only` 只到 partial——v0.2 起必须把“ego 可判性”与“标签值”分列。

## P2：冻结后做正式评测

以下为 2026-10-27 的 P2 状态（原 7 项清单逐项标注完成情况，新增未完成项单列）：

- [x] **确定并冻结 v0.1 谓词/prompt/图像处理/模型与解码参数**：prompt 策略、格式指令、`qwen3.8-max`、temperature=0、`enable_thinking=false`、`max_completion_tokens=256` 已写入冻结清单（[评分契约 §6](WBW/ENACT-USIM-评分契约与统计-20261027.md)）。
- [x] **冻结 v0.1 split/QA/标签/图片清单和协议哈希**：7 组 578 文件，`--verify` 0 退出、篡改自测 5/5（[冻结清单](../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json)）。v0.2/test 冻结**未完成**（见下）。
- [x] **在可支持长度上运行前向/逆向并分方向、分 L、分任务报告**：v0.1 70 题 A/B/C 已完成（[执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)）。
- [x] **运行随机/固定顺序及信息移除基线**：六种程序基线 + 条件 C（去图）+ 条件 D（forward 去动作文本，35 题，oracle 1.0）+ 程序化文本先验基线 0.7714（[评分契约 §4–§5、§11](WBW/ENACT-USIM-评分契约与统计-20261027.md)）。
- [x] **保留固定分母的 EM/TA/PA/格式有效率/错误缺失率**：`usim_strict_v0.3` 已实现固定分母与严格解析，报告含 invalid/missing 计数（[契约测试](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)）。
- [x] **按 episode 分组的 uncertainty**：`report_stats.py` 已实现按 episode 重采样 2000 次的 bootstrap（7 簇，seed 20261024），A/B/C 区间与配对 Δ 已产出（[统计证据](../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.md)）。
- [x] **复核歧义标签与低可见性样本**：round2 盲评复核完成，修正 7 处 `OnSeabed`、2 处可见性、`NextTo` 语义与 notes（[reviewer_a](../data/usim_enact/_review/round2/reviewer_a/review_report.md)、[reviewer_b](../data/usim_enact/_review/round2/reviewer_b/review_report.md)）；v0.2 评估前仍需按新标签整体复评。

### P2 新增项（2026-10-27 状态）

- [x] **v0.2 标注与题集构建**：v0.1 七条已迁移；新增 dev 12 / val 8 共 20 条逐帧标注完成；27 条 episode → 110 关键帧 / 83 转移（81 可见）→ 生成 312 题 → 重排 seed 20261027 → 分层筛选 **120 题**；门禁 audit 通过（多答案=0、空参考转移=0、oracle 1.0）。test 预留 10 条未标注（冻结后才标注）。[v0.2 构建报告](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md)
- [x] **文本先验与条件 D（v0.2 版）**：`text_prior_baseline.py` 升级双模板（v0.1/v0.2 + NearBox），v0.2 inverse **60/60** 文本可解、forward 19/60、总体 0.6583；条件 D（forward 去动作文本）60 题 / 216 图 / oracle 1.0。**A/B/C/D 尚未跑模型**。[协议证据](WBW/ENACT-USIM-v0.2协议证据-20261027.md)
- [x] **v0.2 协议冻结**：13 组 **1818 文件**、payload `6d14fb83…`（`freeze_id=20261027b`，含 B 条件）、`--verify` exit 0、self-test 7/7；test_reserve 与 dev/val/条件 D 零重叠。首版 `20261027`（1374 文件 / `d3370ad2…`）保留作对照。[冻结清单](../data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027b.json)
- [ ] **正式 test**：冻结后标注 test 预留 10 条、构建 test QA，A/B/C/D 与程序基线各跑一次，只报一次、不得据 test 结果调参（[v0.2 方案 §7](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md)）。
- [x] **v0.2 A/B/C/D 首轮模型运行（同版本）**：A/B/C 各 84、D 42，共 294 次请求；A EM 0.9286、B 0.8452、C 0.5952、D 0.6905。离线复核同源码、输入哈希与重新计分均通过；B 为 `completed_with_failures`（8 截断、1 列表长度错误），不把矩阵 exit 0 当全答案合法。
- [ ] **B/A 预算诊断与新 run**：先冻结少量开发诊断题，保持原 prompt／输入／thinking 设置，按格式和停止原因确定预算；新预算比较在独立 run 中运行 A/B，若发布统一四条件表则四条件同预算重跑。旧 256-token 结果保留，禁止仅补答错题后替换分数。
- [ ] **P1 遗留：同版本重跑对照**：v0.1 的 A/B/C 三条件用了 **3 个不同版本的 `run_inference.py`**，正式对照必须同一源码版本重跑；冻结清单已记录漂移（[评分契约 §6.2](WBW/ENACT-USIM-评分契约与统计-20261027.md)）。
- [ ] **思考模式对照**：`enable_thinking=true` + 更大预算，单独 run，不与首轮混分（[执行结果 §11](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)）。
- [x] **B 条件（v0.2 局部放大）**：已构建 120 题 / 432 图，左 panel 与 A 逐字节一致、432/432 可被冻结渲染器复现、程序基线与 A 逐位相同；独立校验 `scripts/usim/check_condition_b.py` → `status=pass`；dev 模型已运行，结果见本轮复核。
- [x] **四条件一键驱动**：`scripts/usim/run_v02_matrix.py` 固定同一 `run_inference.py`/`evaluate.py`（sha 写入 manifest），A=84 / B=84 / C=84 / D=42（dev 过滤），`--dry-run` 四条件全通过；密钥只读 `VLM_API_KEY`，无密钥即拒绝运行（[构建报告 §7.2](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md)）。
- [ ] **test_reserve 10 条标注（2/10 通过结构／源帧检查）**：`001078`、`001650` 各 4 帧／3 个可见非空转移；剩余 8 条待形成正式标注，全部仍需独立质量验收。标注写入 `_expansion/annotation_work/test_reserve/`，**不写 v0.2 数据集**。
- [x] **统计分层初版**：已按 `text_prior` 与 gt 比对形成分层。
- [x] **统计口径与子集契约（2026-10-28 完成）**：分层改称"程序文本基线答对／答错"并逐行带 N（A/B/C 55/29、D 13/29）；`report_stats.py` 新增 `--allow-subset`，显式声明子集后仍需"成员 ⊆ 首条件 + 交集 gt/状态数一致"才返回 0，`integrity` 记录 `declared_subset_ok` 与 `ids_outside_first`；旧 7-episode/70 题固定说明已改为实际数量。四条件报告重跑后 **exit 0**。
- [ ] **B/A 输出预算诊断**：B 的 9 条无效中 8 条为 256 token 截断（`finish_reason=length`），A/C/D 为 0。在 dev 上固定少量覆盖方向×长度的题，仅凭停止原因与格式有效率确定新预算（建议从 1024 起），thinking=false 与 prompt 不变；**不得只重试答错题覆盖旧分数**。若要发布统一四条件表，A/B/C/D 须在新预算下以独立 run_id 重跑并两套并列。

## P3：有了可靠基线后再扩展（2026-10-27：均未开始）

- [ ] 扩至 `L=5…10`，同时报告每类任务能支持的最大长度与有效路径数（v0.2 选帧规范目标 5–6 帧以支持 L=4/5，见 [规范 §3](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)）。
- [ ] 引入导航/巡检/跟随；先建立目标语义、几何和成功条件。
- [ ] 增加 wrist 或双相机条件，保留 ego-only 对照，不能混合为一个分数（round2 已把 wrist 作为辅助证据使用，未进入主结果）。
- [ ] 若能获得 Stonefish 状态/接触/可见性导出，用自动流程替代人工环节并核验一致性。
- [ ] 再考虑训练、SFT/LoRA、浑浊度/光照等控制实验；每项另有独立的验证选择与测试协议。

## 当前有效命令（2026-10-27）

以下命令适用于 PowerShell。Python 统一使用：

```powershell
Set-Location E:\code\UW-VLM\ENACT
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
```

### 0）契约与冻结自检（不需要密钥）

```powershell
# 评分契约 (a)–(f)：多答案/不可交换/空签名拒绝/固定分母/重复ID/v0.1 回归
& $py -m scripts.usim.check_scoring_contract_v2
# 冻结工具自测（篡改检测 5 项）
& $py -m scripts.usim.freeze_protocol --self-test
```

### 1）v0.2 数据与题集构建（当前主流程）

```powershell
$v2  = 'data\usim_enact\usim-enact-v0.2'
$run = 'data\usim_enact\runs\qwen3.8-max\v02_dev_001'

# 标注 → 数据集（manifest/场景图/图片）
& $py -m scripts.usim.build_dataset --annotations "$v2\annotations\episodes" --out $v2

# QA 生成 → 固定 seed 重排 → 按长度配额筛选（规则先于模型结果冻结）
& $py -m scripts.usim.build_qa --data-root $v2 --step-lengths 3,4,5 --num-to-sample 25
& $py -m scripts.usim.reseed_answers --data-root $v2 --qa "$v2\QA\train\enact_ordering.jsonl" --seed 20261027
& $py -m scripts.usim.curate_qa_v02 --data-root $v2 --qa "$v2\QA\train\enact_ordering.jsonl" --out "$v2\QA\train\enact_ordering_curated.jsonl"
```

### 2）门禁：有效性审计、oracle、划分、条件 D、冻结

```powershell
$qa = "$v2\QA\train\enact_ordering_curated.jsonl"

# 排列枚举 + 精确机会水平 + 参考排列/空签名 gate
& $py -m scripts.usim.audit_qa_validity --data-root $v2 --qa $qa --out data\usim_enact\_protocol\audit_qa_validity_v0.2.json
# 合成 oracle 必须全 1.0
& $py -m scripts.usim.evaluate --data-root $v2 --qa $qa --synthetic oracle --out "$run\baseline_oracle.json"
# dev/val 输入划分（按 episode；test 冻结后另建）
& $py -m scripts.usim.make_splits_v02 --qa $qa --out-dir "$run\inputs"
# 条件 D：forward 去动作文本（纯视觉排序）
& $py -m scripts.usim.build_condition_d --data-root $v2 --qa $qa --out "$v2\QA\train\enact_ordering_curated_no_text.jsonl"
# v0.2 冻结（参数见评分契约 §6.3；--verify 必须 0 退出）
& $py -m scripts.usim.freeze_protocol --data-root $v2 --run-dir $run --freeze-id <YYYYMMDD>
& $py -m scripts.usim.freeze_protocol --verify data\usim_enact\_protocol\freeze_usim-enact-v0.2_<YYYYMMDD>.json
```

### 3）真实模型（无 `VLM_API_KEY` 只能 dry-run；A/B/C/D 必须同一源码版本）

```powershell
$env:VLM_API_URL    = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
$env:VLM_MODEL_NAME = 'qwen3.8-max'
$env:VLM_API_KEY    = '<本会话设置，不落盘>'

# 无密钥时先做输入/资产校验
& $py -m scripts.usim.run_inference --qa "$run\inputs\full_dev_v02.jsonl" --out "$run\A\predictions.jsonl" --dry-run
# 有密钥后按条件 A/B/C/D 分别输出到独立目录，再用 evaluate.py + report_stats.py 出表
```

v0.1 的复跑命令（契约/统计/文本先验/冻结/三条件评测）见 [07 §8](07_reproduction_run.md) 与 [评分契约 §8](WBW/ENACT-USIM-评分契约与统计-20261027.md)。上游 `enact qa` / `enact eval` CLI 不适用于当前水下数据（见文末历史备注）。

## 历史备注（2026-10-23，保留；已过时部分仅作记录）

### 建议新建的正式环境（历史，未按此执行）

```powershell
conda create -n enact-usim python=3.10 -y
conda activate enact-usim
Set-Location E:\code\UW-VLM\ENACT
python -m pip install -e .
python -m pip install pyarrow==23.0.1
enact --help
python -m pip freeze > docs/evidence/enact_usim_environment.txt
```

实际运行未建该 conda 环境，统一使用上文 `$py` 路径；依赖版本未锁定（待核实）。上游 `--seed` 被 generator 内部 42 重置的问题未修复，不能据此设计多种子实验。

### 上游 CLI 示例（历史，不适用于当前水下数据）

```powershell
# 仅适用于已编译好的 ENACT 格式输入，不可直接指向 usim/test/data
enact qa data/replayed_usim_segmented data/replayed_usim data/QA/enact_ordering.jsonl --num-to-sample 5

# predictions 需要模型 runner 生成；当前已有 scripts/usim/run_inference.py + evaluate.py 闭环
enact eval data/predictions/enact_ordering_mymodel.jsonl `
  --segmented-data data/replayed_usim_segmented `
  --raw-data data/replayed_usim `
  --output-root data/evaluation/usim_pilot
```

以上两条为 2026-10-23 记录的上游 CLI 条件性调用示例；当前水下目录与预测产物已存在，但评测统一走 `scripts/usim/evaluate.py`，不使用上游 eval 入口。

## 仍需要你掌握或补充的信息

1. **语义真值来源：** 已按人工标注路线推进（v0.1 完成、v0.2 进行中）；Stonefish 场景/接触状态自动导出仍未接入（[03 §8](03_usim_data_audit.md)）。若后续能导出真值，可替代部分人工判断。
2. **控制字段说明：** 夹爪（`state[0]`）与离底高度（`state[28]`）已作辅助证据使用；关节/推进器映射、单位与 `target_pos` 语义**待核实**，未知信息不猜测写进标签（[03 §3–§4](03_usim_data_audit.md)）。
3. **推理资源：** 已使用 DashScope API 的 `qwen3.8-max`（密钥仅经环境变量注入、不落盘；单价未核实，不折算金额）。当前会话无 `VLM_API_KEY`，正式批量实验与 test 需先补密钥。

当前最值得投入的下一项工作是：**完成 v0.2 新增 20 条 dev/val 标注与数据/题集构建门禁，随后做 v0.2 协议冻结与正式 test。**
