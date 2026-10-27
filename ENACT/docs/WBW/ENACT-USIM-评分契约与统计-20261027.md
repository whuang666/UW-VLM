# ENACT-USIM 评分契约与统计（协议冻结侧）

日期：2026-10-27（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。数据集：`usim-enact-v0.1`（7 episode / 28 帧 / 70 题）。评分协议：`usim_strict_v0.2`（`scripts/usim/evaluate.py`）。
角色：protocol-engineer（评分/统计/冻结）。对应共享任务 `task-4`；上游依据见 [执行结果](../WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)、[复核与补充清单](../WBW/ENACT-USIM试运行复核与补充清单-20261024.md) §2–3、[数据与评测协议草案](../06_data_and_evaluation_contract.md)、[API 实施方案](../WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md) §7/§10。

**本轮未改动任何 v0.1 数据、QA、图片或既有脚本**（`evaluate.py`/`run_inference.py`/`build_qa.py` 等均未编辑）；只新增 5 个脚本、`data/usim_enact/_protocol/` 下的证据与本报告。

## 摘要（可直接引用的结论）

| # | 结论 | 证据 |
|---|---|---|
| 1 | **v0.1 每题恰好 1 个 TA 接受排列（多答案题 = 0）**，70 题全部如此；参考答案被自身 verifier 接受、identity 排列接受率 0.4714。独立枚举复算与已发布数字完全一致：随机 EM/TA **0.4333**、随机 PA_item **0.5167**、随机 PA_transition **0.5000**、identity EM **0.4714**。 | [audit_qa_validity_usim-enact-v0.1.json](../../data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.1.json) |
| 2 | **0 个参考转移的可见签名是空集**（v0.1 数据本身没有"空签名虚假通过"问题），但 `usim_strict_v0.2` 的评分器**不拒绝**这种题：合成证据显示空签名题会让 2/2 个排列全部 TA=1。提出 `usim_strict_v0.3` 参考实现（guard 拒绝 + 记 0 分），5 项契约测试全过。 | [check_scoring_contract_v2.json](../../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json) |
| 3 | A/B/C 三条件按 episode 分组 bootstrap：**A EM 0.9571 [0.8714, 1.0000]、B 0.9286 [0.8143, 1.0000]、C 0.7286 [0.6714, 0.8000]**（7 episode 重采样 2000 次，seed 20261024）。A−C 配对 ΔEM **+0.2285 [+0.1285, +0.3143]**；A−B ΔEM **+0.0285 [+0.0000, +0.0572]**（CI 下界触 0，只能表述为"无可测增益"）。 | [report_stats_dev_ego_thinking_false_001.json](../../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.json) / [.md](../../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.md) |
| 4 | **确定性文本先验基线（不看图）总体 EM 0.7714 / PA_item 0.8024**，**高于**去图模型 C 的 0.7286（Δ=+0.0428；54 题 vs 51 题正确，23 题答案不同）。inverse 组文本基线 **35/35 全对**（文本可解），forward 组 19/35。**条件 C 的分数完全可由文本先验解释，模型在其中并未超出该基线。** | [text_prior_baseline_usim-enact-v0.1.json](../../data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json) |
| 5 | 由 #4 重算视觉净增益：A 比文本先验基线多 **+13/70 = +18.57pp**；分方向看 **inverse 34/35（文本 35/35，无增益）**、**forward 33/35 vs 19/35（+40.0pp，唯一干净视觉证据）**。此前用 C 得到的"+0.229 视觉增益"应改写为"相对确定性文本基线 +0.186"。 | 同上 |
| 6 | 已生成 v0.1 协议冻结清单：**7 组共 578 个文件**（标签 21、图片 504、QA 4、run 输入 4、run 产物 26、代码 18、数据集 manifest 1），带分组摘要与 `manifest_payload_sha256`；`--verify` 退出 0，篡改自测 5/5 检出。**发现 A/B/C 三次 run 使用了 3 个不同版本的 `run_inference.py`（哈希漂移）**，已记录，正式对照前建议统一代码重跑。 | [freeze_usim-enact-v0.1_20261027.json](../../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json) / [.verify.json](../../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.verify.json) |

## 1. 交付物

全部为**新文件**；均可在 `ENACT/` 下用 `python -m scripts.usim.<name>` 或直接路径运行。

| 文件 | 作用 |
|---|---|
| `scripts/usim/audit_qa_validity.py` | 枚举每题全部合法排列，用真实 verifier 判定语义接受集；输出多答案数、接受集大小、gt/identity 是否被接受、精确随机 EM/TA/PA 期望、direction×L 汇总；对 v0.2 同样适用（`--data-root/--qa`）。硬错误（重复 ID、gt 被拒、空参考转移、已知 v0.1 数字不符）返回非零。 |
| `scripts/usim/check_scoring_contract_v2.py` | 合成数据契约测试 (a) 多合法顺序；(b) 不可交换动作交换；(c) 空签名/空可见转移拒绝；(d) 固定分母 + 严格解析边界；(e) 重复/未知 ID 拒绝。任一失败非零；内置 `ScoringContractV2` 作为 v0.3 可执行参考规范。 |
| `scripts/usim/report_stats.py` | 从 `report.items.jsonl` 生成 direction×L×任务/ episode 表、按 episode 重采样的 bootstrap CI、A/B/C 同 ID 配对计数与配对 bootstrap、失败/格式错误计数；固定 seed，输出稳定 JSON+Markdown。 |
| `scripts/usim/text_prior_baseline.py` | 仅从 `question` 解析 `[Action N]` 文本，按生命周期词序构造确定性排序基线（不看图、不看 gt），在 v0.1 上算 EM/PA，统计 identity 答案率与机会，并与去图条件 C 对照。 |
| `scripts/usim/freeze_protocol.py` | 生成/校验协议冻结 manifest（标签、QA、图片清单、prompt/格式指令、模型/解码参数、评分版本、split/seed、代码与 run 产物的 SHA-256 汇总；版本号+时间戳；`--verify` 非零/零退出；`--self-test` 篡改检测）。 |
| `data/usim_enact/_protocol/**` | 上述脚本产出的机器可读证据（见附录 A）。 |
| 本报告 | 证据、命令、结论与建议。 |

## 2. v0.1 QA 有效性独立审计（多答案=0 的确认）

方法：对每个冻结题用真实 `USIMVerifier`（与 `evaluate.py` 完全同一路径）枚举全部 `(L−1)!` 个排列（L=3 → 2 个，L=4 → 6 个），记录 TA/EM/PA；随机基线按"均匀抽一个合法排列"求**精确期望**（枚举而非单次随机）。参考转移签名由 verifier 对正确时间线做 partial diff 得到。

### 2.1 每设定接受集与精确机会水平

| 设定 | N | 每题接受排列数 | 多答案题 | 随机 EM | 随机 TA | 随机 PA_item | 随机 PA_micro | identity EM | 空参考转移 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| forward L3 | 28 | 均为 1 | 0 | 0.5000 | 0.5000 | 0.6250 | 0.6250 | 0.6071 | 0 |
| forward L4 | 7 | 均为 1 | 0 | 0.1667 | 0.1667 | 0.3333 | 0.3333 | 0.2857 | 0 |
| inverse L3 | 28 | 均为 1 | 0 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0.4643 | 0 |
| inverse L4 | 7 | 均为 1 | 0 | 0.1667 | 0.1667 | 0.3333 | 0.3333 | 0.1429 | 0 |
| **合计** | **70** | **{1: 70}** | **0** | **0.4333** | **0.4333** | **0.5167** | **0.5000** | **0.4714** | **0** |

- 70 题的参考排列全部被 verifier 接受（`gt_rejected_questions=0`），identity 排列的接受率与 identity EM 都是 0.4714 → identity 答案若被接受，等价于恒等参考。
- 每题接受集大小直方图为 `{"1": 70}`：**TA 与 EM 在 v0.1 上必然数值相等**，`semantic_only` 恒为 0。这既确认了已发布数字，也说明 **v0.1 没有验证"多个语义合法顺序"的评分路径**；该路径只能由合成契约测试覆盖（§3a）。
- 与 docs/WBW 已发布数字逐项一致（脚本内 `cross_checks_v0_1` 全部 pass，容差 5e-5）：随机 EM 0.4333、PA_item 0.5167、PA_micro 0.5000、identity 0.4714、四组题量 28/7/28/7。
- 六种程序基线重算并与 `data/usim_enact/usim-enact-v0.1/evaluation/baseline_*/report.json` 对照（共享字段全部相同）：

| 基线 | EM | TA | PA_item | PA_micro |
|---|---:|---:|---:|---:|
| oracle | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| identity | 0.4714 | 0.4714 | 0.5214 | 0.5130 |
| reverse | 0.3857 | 0.3857 | 0.5071 | 0.4805 |
| random（seed=0 单次） | 0.3571 | 0.3571 | 0.4548 | 0.4416 |
| empty | 0 | 0 | 0 | 0 |
| malformed | 0 | 0 | 0 | 0 |

> 注：存档的 `evaluation/baseline_*/report.json` 由旧构建产出，缺少当前 `evaluate.py` 的 `invalid_reasons` 与 `transitions_total` 字段；共享指标逐项相同（脚本记录 `fields_only_in_recomputed`），不影响数字但说明存档报告与现行评分器存在**字段级版本差**。

## 3. 评分契约 v2 测试（`usim_strict_v0.3` 提案）

证据：[check_scoring_contract_v2.json](../../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)（`all_pass=true`）。测试通过内存中的合成场景图（stub `SceneGraphReader`）驱动真实 `USIMVerifier` 与 `USIMEvaluator.summarise`，不写任何 v0.1 文件；仅 (e) 读取真实 `evaluate.main` 的错误码行为。

| 测试 | 场景 | 断言 | 结果 |
|---|---|---|---|
| (a) 多合法顺序 | 合成转移使 `[1,2]` 与 `[2,1]` 都是参考签名的语义超集 | 两者 TA=1；只有参考 EM=1；汇总 EM=0.5、TA=1.0、semantic_only=0.5、PA_item=1.0 | ✅ |
| (b) 不可交换动作 | grasp→lift 交换后参考签名不再是输入子集（forward 与 inverse 各一例） | 参考 TA=1、交换 TA=0；接受集仅 `{参考}` | ✅ |
| (c) 空签名 / 空可见转移 | ① 参考转移 diff 为空集；② 底层有变化但 ego 不可见（可见签名空） | 先记录**上游 verifier 的虚假通过**：2/2 排列 TA=1；v0.3 guard 将该题标 `invalid_reference_transitions` 并计 0；整批预检查抛 `ContractViolation` | ✅（风险已复现，guard 有效） |
| (d) 固定分母 + 严格解析 | L=3 全对 + L=4 缺失；解释文本/多数组/非排列/布尔/截断/空/缺失 | `PA_transition_micro = 2/(2+3) = 0.4`、PA_item=0.5、EM=0.5、invalid_or_missing=1（reason=missing）；`Explanation: [1, 2]` 整题 invalid 计 0 | ✅ |
| (e) 重复/未知 ID | 对真实一题构造合法/重复/未知预测文件，调用 `evaluate.main` | 合法文件 exit 0 且写出报告；重复与未知 ID 均 exit 2 且**不写报告**；`load_predictions` 报重复 | ✅ |

**发现（P0，需 Lead 决策是否落地）**：`usim_strict_v0.2` 的 `evaluate.py` 对"参考转移可见签名为空"没有任何 guard。此时空集是任何集合的子集，verifier 会**对任意排列给 TA=1**——合成实测 2/2 排列通过。v0.1 数据经审计为 0 个空参考转移，因此**不影响已发布的 v0.1 数字**；但 v0.2 一旦出现"不可见变化/漏标"就被编译成空签名，就会产生虚假满分。`check_scoring_contract_v2.py` 内的 `ScoringContractV2` 已是可执行参考实现（参考转移 guard + 计 0 + 批量预检查），建议在 v0.2 评分器升级时并入 `evaluate.py`（按约束需 Lead 批准后改动）。

## 4. 统计口径与 A/B/C 结果

证据：[report_stats_dev_ego_thinking_false_001.json](../../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.json) / [.md](../../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.md)。方法：从三条件 `report.items.jsonl` 重建指标（不重新评分）；ID 集合、`gt`、`num_states` 跨条件一致性校验通过（各 70 ID、0 冲突）；bootstrap 以 **episode (`task_name`) 为重采样单位**（7 个簇，2000 次，seed 20261024，百分位 95%），同一 episode 的所有题/方向同时进出；固定 seed 下 JSON 与 Markdown 两次运行字节级一致。

### 4.1 条件总览与 direction×L

| 条件 | N | EM | TA | PA_item | PA_micro | invalid/missing | identity 答案率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A 原图（full_v1） | 70 | 0.9571 | 0.9571 | 0.9619 | 0.9610 | 0 | 0.5000 |
| B 全图+局部（condB_zoom） | 70 | 0.9286 | 0.9286 | 0.9333 | 0.9351 | 0 | 0.4714 |
| C 去图（condC_text_only） | 70 | 0.7286 | 0.7286 | 0.7810 | 0.7662 | 0 | 0.4286 |

（identity 参考率 = 0.4714；三条件 run_status 均 `completed`、planned=answered=success=70、truncated/invalid/failed/missing=0。）

| setting | N | A EM | B EM | C EM | A PA_micro | B PA_micro | C PA_micro |
|---|---:|---:|---:|---:|---:|---:|---:|
| forward L3 | 28 | 0.9643 | 0.9643 | 0.6071 | 0.9643 | 0.9643 | 0.7143 |
| forward L4 | 7 | 0.8571 | 0.8571 | 0.1429 | 0.9048 | 0.9048 | 0.2381 |
| inverse L3 | 28 | 0.9643 | 0.8929 | 0.9286 | 0.9643 | 0.8929 | 0.9286 |
| inverse L4 | 7 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

分方向 bootstrap（EM）：A forward 0.9429 [0.8286, 1.0] / inverse 0.9714 [0.9143, 1.0]；C forward 0.5143 [0.3714, 0.6571] / inverse 0.9429 [0.8857, 1.0]。**C 的低分集中在 forward（尤其 L4：7 题仅 1 对），inverse 在无图时已接近满分**——与执行结果文档 §6 的定性结论一致，但本轮用"文本先验基线"给出了更强的定量解释（§5）。

### 4.2 episode 与任务分组（EM）

| episode | 任务文本 | A | B | C |
|---|---|---:|---:|---:|
| usim_train_episode_000200 | Pick up the blue cylinder | 0.7000 (n=10) | 0.6000 | 0.7000 |
| usim_train_episode_000201 | Pick up the blue cylinder | 1.0000 | 1.0000 | 0.7000 |
| usim_train_episode_000552 | Pick up the red cylinder | 1.0000 | 0.9000 | 0.9000 |
| usim_train_episode_000553 | Pick up the red cylinder | 1.0000 | 1.0000 | 0.7000 |
| usim_train_episode_000555 | Pick up the red cylinder | 1.0000 | 1.0000 | 0.6000 |
| usim_train_episode_000556 | Pick up the red cylinder | 1.0000 | 1.0000 | 0.7000 |
| usim_train_episode_001302 | Pick up the red cylinder and transfer it to the box | 1.0000 | 1.0000 | 0.8000 |

任务分组：blue cylinder（20 题）A/B/C = 0.8500/0.8000/0.7000；red cylinder（40 题）= 1.0000/0.9750/0.7250；red+transfer（10 题）= 1.0000/1.0000/0.8000。**A 的 3 处错误全部落在 episode 000200；B 的 5 处错误中 4 处也在该 episode（另 1 处在 000552）**。这提示后续复核/难度扩展应优先看该 episode 的标签与视觉可判定性，而不是扩大同类 "Pick up red cylinder" 题量。

### 4.3 配对比较（同 70 ID）

| 比较 | both_correct | both_wrong | only_first | only_second | ΔEM [95% CI] | ΔPA_item [95% CI] |
|---|---:|---:|---:|---:|---|---|
| A vs B | 65 | 3 | 2 | 0 | +0.0285 [+0.0000, +0.0572] | +0.0286 [+0.0000, +0.0571] |
| A vs C | 50 | 2 | 17 | 1 | +0.2285 [+0.1285, +0.3143] | +0.1809 [+0.0809, +0.2714] |
| B vs C | 48 | 2 | 17 | 3 | +0.2000 [+0.0714, +0.3143] | +0.1523 [+0.0285, +0.2595] |

分设定（ΔEM）：A−C 在 forward L3 为 **+0.3572 [+0.1786, +0.5357]**、forward L4 为 **+0.7142 [+0.4285, +1.0]**、inverse L3 为 +0.0357 [0, +0.1072]、inverse L4 为 0；A−B 只在 inverse L3 有 +0.0714 [0, +0.1429]（B 在该组错 2 题），其余 0。**A/B 的差异在统计上不可区分（CI 下界=0），只能表述为"本轮无可测增益"；A/C 的视觉差异主要来自 forward L3/L4。**

### 4.4 统计口径建议（建议作为 v0.2 报告规范）

1. **主表必须按 direction×L** 展开：冻结 N、有效排列数、invalid/missing 数与原因、EM、TA、PA_item、PA_transition_micro，并与**随机期望 + identity 期望**并列；不能只报混合总分。
2. **70 题不是 70 条独立轨迹**：总体区间一律用按 episode 分组的 bootstrap（重采样 episode，同簇题目/方向整体进出），并注明 episode 数（7）；direction×L 单元只有 7 题、CI 更宽，只能作开发诊断。不得用题级二项 CI 冒充。
3. **A/B/C 必须配对同 ID**：同时报告 both/only 计数与配对 bootstrap 的 Δ；失败题固定分母计 0，不因模型答错而删题。
4. **TA 必须与多答案计数一起报**：v0.1 为 0 多答案，此时 TA≡EM、没有独立信息；报 TA 时应同时报 `multi_answer_questions`（本审计脚本可直接产出）。
5. **identity 答案率与机会并列报**：v0.1 参考 identity 率 0.4714；模型 A/B/C 的 identity 答案率为 0.50/0.4714/0.4286，因此"高分"里恒等先验占多大比例必须显式说明。
6. **任何对外结论都带条件 C + 文本先验基线**（§5）：C 只说明"去图模型能拿多少"，文本先验基线说明"完全不看图、只用文本能拿多少"，后者才是捷径量化的下界/参照。
7. 开发集结论与最终 test 结论分开；镜像/文档中的历史数字注明产生它的评分器版本（`usim_strict_v0.2`）与证据文件。

## 5. 文本先验基线（捷径量化）

证据：[text_prior_baseline_usim-enact-v0.1.json](../../data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json)。规则版本 `text_lifecycle_v1`，**只读 `question` 字段**（不读 `gt_answer`/`images`/`key_frame_ids`/任何模型预测），规则在看模型结果前从数据 schema 与 `enact/adapters/usim_translator.py` 的谓词生命周期冻结：

| 生命周期阶段 | 谓词 | 文本模式 |
|---:|---|---|
| 0 | OnSeabed | `on the seabed` |
| 1 | NextTo | `next to` |
| 2 | InGripper | `grasped by the robot` |
| 3 | Lifted | `lifted above the seabed` |
| 4 | InBox | `inside the (green) box` |

- **inverse**：解析 `## Shuffled Actions` 的 `[Action N] <描述>`，对每行动作取"非否定句中出现的最高阶段"（否定句守卫：`no longer`、`not … anymore`、`stopped being` 等不贡献阶段），按 `(阶段升序, 标签升序)` 排序作为答案。样例：`[Action 1] grasped … is not on the seabed anymore`（阶段 2）、`[Action 2] lifted …`（阶段 3）→ 预测 `[1,2]`。
- **forward**：题目 `## Actions in Order` 已按时间顺序给出动作文本，但**不含"future-image 标签 → 动作"的映射**，文本无法消解标签顺序；故采用固定标签先验（恒等排列），并在证据中记录该假设（`label_mapping_available_in_text=false`；35 题的动作列表全部按阶段非降序给出）。
- 设计说明：规则利用的是数据 schema 层面的词表先验（物体生命周期单调），这是**文本先验的定义本身**，不是从模型成绩或 gt 反推的参数；inverse 动作行即参考转移的自然语言描述，所以 35/35 可解。

### 5.1 结果（真实 verifier 评分）

| 设定 | N | 文本基线 EM | TA | PA_item | PA_micro | identity 答案率 | identity 参考率 | 随机 EM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| forward L3 | 28 | 0.6071 | 0.6071 | 0.6250 | 0.6250 | 1.0 | 0.6071 | 0.5000 |
| forward L4 | 7 | 0.2857 | 0.2857 | 0.5238 | 0.5238 | 1.0 | 0.2857 | 0.1667 |
| inverse L3 | 28 | **1.0000** | 1.0000 | 1.0000 | 1.0000 | 0.4643 | 0.4643 | 0.5000 |
| inverse L4 | 7 | **1.0000** | 1.0000 | 1.0000 | 1.0000 | 0.1429 | 0.1429 | 0.1667 |
| **合计** | **70** | **0.7714** | 0.7714 | 0.8024 | 0.7987 | 0.7000 | 0.4714 | 0.4333 |

### 5.2 与去图条件 C 对照

| 指标 | 文本基线 | 条件 C（模型去图） | 差 |
|---|---:|---:|---:|
| 总体 EM | **0.7714（54/70）** | 0.7286（51/70） | **+0.0428（基线高 3 题）** |
| 总体 PA_item | 0.8024 | 0.7810 | +0.0214 |
| 配对：both correct / 仅基线对 / 仅 C 对 / both wrong | — | — | 43 / **11** / 8 / 8 |
| 不同答案的题数 | — | — | 23/70 |

按设定：forward L3 基线=C=0.6071（模型 C 在该组恰好是恒等先验，与基线一致）；forward L4 基线 0.2857 > C 0.1429（C 在 L4 反而低于恒等先验）；inverse L3 基线 1.0 > C 0.9286；inverse L4 两者均 1.0。

**解读**：
1. **C 的 0.7286 完全落在文本先验可解释范围内**——一个不看图的确定性排序规则就比它高 3 题。因此"模型有 0.73 的文本理解能力"不能作为结论；更准确的表述是"文本先验约 0.77，模型在文本可解题上没有跑赢先验"。
2. **inverse 组（35/35）是文本可解题**，因此 A 在该组的高分（34/35）不能作为视觉能力证据——这与执行结果文档 §6 的结论一致，但更严格：不仅是"接近"，而是文本已经**完全决定**答案。
3. **forward 组是唯一能测视觉的设定**：文本基线 19/35 = 0.5429（forward 预测全部为恒等排列，因此该分数完全来自标签位置先验），A 33/35 = 0.9429，**净视觉增益 +40.0pp**；整体 A 相对文本先验 +18.57pp（+13/70）。
4. 限制：forward 的恒等先验只是"标签位置先验"，不是文本信息上限；inverse 规则使用了词表先验（这正是文本先验的定义）；L=4 的 forward 只有 7 题，PA 差异噪声大；v0.2 若动作词表扩展，需检查 `unresolved_labels` 并复跑（脚本已输出）。

## 6. 协议冻结（v0.1 基准）

证据：[freeze_usim-enact-v0.1_20261027.json](../../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json)（159 KB）、校验报告 [freeze_usim-enact-v0.1_20261027.verify.json](../../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.verify.json)。`freeze_id=20261027`，`created_at` 为 Asia/Shanghai 时间戳，manifest 自带 `schema=usim-protocol-freeze/v1` 与 `manifest_payload_sha256`（对除该字段外的规范 JSON 求 SHA-256），因此**连 manifest 本身被后改也可检出**。

### 6.1 冻结内容（7 组，共 578 个文件）

| 组 | 文件数 | 内容 | 本次摘要（SHA-256） |
|---|---:|---|---|
| labels | 21 | 7 份 episode 标注 + 7 份 raw scene graph + 7 份 segmented scene graph | `ef5b7fa1b80dfbcd748257d52a18e4fa60c655f60b67c8ea2499ec80a4e78e35` |
| images | 504 | 224 张 A 条件题面图 + 224 张 B 条件图 + 28 张 raw 帧 + 28 张 segmented 帧 | `b6ee1db5a94735bec0afdc232cd0df09c125fda3795a23bcf4041a812340be04` |
| qa | 4 | `QA/train/enact_ordering.jsonl`、B 条件 QA、两份 build summary/manifest | `95db9c828e266f5518b26b8d508aa63e2621d543dc55c23e5fc0f0b446263df1` |
| run_inputs | 4 | `preflight.jsonl`/`smoke.jsonl`/`full_dev.jsonl`/`splits_manifest.json` | `b18f4d7832a92ebc345de8aac30bac2efe7c5bf53fc301d6948c9e970b531348` |
| run_artifacts | 26 | 三条件的 run_config/input_manifest/predictions/report/items/run_status/attempts/responses | `6c7b61129f20795db415e7e459404cee3dd90a57fda416d16f81a848d02e7f7e` |
| code | 18 | `evaluate.py`、`run_inference.py`、`build_qa.py`、adapter/evaluator/translator 等 | `a09f35d1e9d6b24684a3961c4f5d2ada2b0e9ad35487c8ccf865a5820ae5f576` |
| dataset_manifest | 1 | `data/usim_enact/usim-enact-v0.1/manifest.json` | `f2d0df7f60d72b7975b454fa8f4de1f3d6f85fc1a279f8a20941a5a5c4c0bee3` |

除逐文件哈希外，还**语义化记录**：dataset `protocol_version/counts/episodes`；prompt（policy=`option_a_no_system_message`、system_prompt=null、格式指令全文与 sha）；model（`qwen3.8-max`，temperature 0、enable_thinking false、max_completion_tokens 256、stream false、timeout 180、attempts 3、DashScope 完整 URL；三条件解码参数一致）；scoring（`usim_strict_v0.2`、`evaluate.py` sha `9d137a19…`、parser=`strict_permutation_v1`、固定分母、known_gaps）；split（seed 20261024、`make_splits.py` sha、`splits_manifest.json` sha 与其中源 QA 哈希/文件哈希校验、输入 ID 覆盖校验）；run（三条件 run_status 与模型回显）。

生成时交叉校验（`generation_checks.all_hard_checks_pass=true`）：dataset manifest 的 7 份标注哈希、56 个帧哈希全部匹配；三条件 `qa_sha256` 与输入文件一致、`image_manifest_sha256` 由 `input_manifest.records` 重算一致、格式指令 sha 重算一致、run 均 completed；split 源 QA 哈希/文件哈希/seed 一致；`full_dev.jsonl` 记录与源 QA 逐条相等、覆盖全部 70 ID；三条件 prompt 与解码参数一致。

### 6.2 关键发现：推理脚本在三条件间漂移

冻结清单按 `run_config.code_sha256` 记录了三条件各自使用的代码版本，并标记 drift：

| 条件 | `run_inference.py` 记录哈希 |
|---|---|
| full_v1（A） | `4a9c46a790a0ed28126c2e570834a86504571d2869f74f63dfa72f582f0d6605` |
| condC_text_only（C） | `2349b0610990ec954e15bf77d30d7c034b2b745b30c16b932198e1245cf11c61` |
| condB_zoom（B） | `4cfc3a5acdcdb1346e214f8473b44347cac1b2aa1653df31ba3d39c853dffad9`（= 当前文件） |

`evaluate.py`（sha `9d137a19…`）与所有 adapter 在三条件间一致，QA/prompt/模型/解码参数也一致；但**推理器版本 A/B/C 各不相同**。这会影响"同代码对照"的严格性。建议：正式/对外结果使用**同一个提交**的三条件重跑（或至少把 v0.1 的三次 run 用统一推理器重跑后再发布对照差值）；在此之前，冻结清单会把漂移固定记录，避免以后被悄悄覆盖。

### 6.3 用法与 v0.2 冻结模板

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'

# 生成（v0.1 基准，本次已执行）
& $py -m scripts.usim.freeze_protocol --freeze-id 20261027

# 校验：0 = 全部一致；2 = 有缺失/新增/哈希不符/manifest 被改
& $py -m scripts.usim.freeze_protocol --verify `
    data\usim_enact\_protocol\freeze_usim-enact-v0.1_20261027.json `
    --verify-out data\usim_enact\_protocol\freeze_usim-enact-v0.1_20261027.verify.json

# 篡改检测自测（5 项，全部应 PASS）
& $py -m scripts.usim.freeze_protocol --self-test

# v0.2（待 Lead 接入数据/run 后）：--condition 按实际目录命名重复传入
& $py -m scripts.usim.freeze_protocol --data-root data\usim_enact\usim-enact-v0.2 `
    --run-dir 'data\usim_enact\runs\<model>\<run-label>' `
    --condition A=<dir> --condition B=<dir> --condition C=<dir> `
    --freeze-id <YYYYMMDD>
& $py -m scripts.usim.freeze_protocol --verify data\usim_enact\_protocol\freeze_usim-enact-v0.2_<YYYYMMDD>.json
& $py -m scripts.usim.audit_qa_validity --data-root data\usim_enact\usim-enact-v0.2   # v0.2 有效性 gate
```

`--verify` 会重算逐文件哈希、按记录的通配模式重扫目录（可发现新增/删除文件）、重算分组摘要与 manifest payload 哈希；v0.2 冻结建议在**正式推理前**生成一次（输入冻结），推理后再生成一次 run 级清单或把 run 产物追加到新 freez_id。冻结清单记录绝对 `root`；换机器校验用 `--root` 覆盖。

### 6.4 冻结字段建议（v0.2 起的最小集合）

以下字段缺一不可（本工具已全部实现，v0.2 只需换 `--data-root/--run-dir`）：

| 类别 | 必须冻结的字段 | 理由 |
|---|---|---|
| 数据版本 | `protocol_version`、dataset `manifest.json` 的 sha 与 counts/episodes | 区分"换评分"还是"换数据"；v0.1→v0.2 必须可分辨 |
| 标签 | 全部 episode 标注、raw/segmented scene graph 的逐文件 sha + 分组摘要 | 标签是唯一语义真值来源，任何后改都必须可见 |
| QA | 源 QA JSONL、run 输入（preflight/smoke/full_dev）、split 清单及 seed、按 QA 的逐条哈希校验 | 题面/重排/参考排列变化会直接改变分数；run 实际用的是 run 输入而非源文件，两者都要记 |
| 图片 | QA 题面图（A/B 条件）与 raw/segmented 帧的逐文件 sha + 计数 | 输入图像是条件差异的主体；放大/裁剪规则文件（B 条件 build manifest）也要入清单 |
| prompt | prompt policy（方案 A 无 system message）、system prompt、格式指令**全文与 sha** | 该模型无 system message 时会自由推理，格式指令是必备 prompt 组成部分（执行结果 §3） |
| 模型/解码 | model_requested + 响应回显 model、temperature、enable_thinking、max_completion_tokens、stream、timeout、max_attempts、完整 API URL | 别名模型可能指向不同快照；解码参数变化会使对照不可比 |
| 评分 | 评分协议名、`evaluate.py` sha、parser 语义版本、固定分母规则、指标定义、known_gaps | 评分器改动必须可追溯；本轮已发现 v0.2 的空签名 gap |
| 代码 | adapter/evaluator/translator/generator/推理器 sha，并与各 run_config 记录值做 drift 对照 | `git HEAD` 不覆盖未跟踪文件；本轮的推理器漂移正是靠此暴露 |
| run 产物 | 每条件 run_config/input_manifest/predictions/report/run_status/attempts/responses 的 sha 与完成状态 | 成绩可追溯到原始响应与配置，失败计数不丢失 |
| 元信息 | `freeze_id` + `created_at`、`manifest_payload_sha256` | 版本号+时间戳 + 防后改；换机器校验用 `--root` |

建议同时把 **`image_condition`、`run_label`、`source_model_commit`** 写入 v0.2 的 `run_config.json`（v0.1 的 `full_v1` 缺 `image_condition`，只能靠 input_manifest 的 image tokens 间接确认）。

## 7. 发现的问题与建议

| 级别 | 问题 | 证据 | 建议 |
|---|---|---|---|
| **P0** | `usim_strict_v0.2` 不拒绝"参考转移可见签名为空"的题，verifier 会对任意排列给 TA=1（虚假语义通过） | §3(c)；`ScoringContractV2` | 按 docs/06 §6 在 v0.2 评分器中加参考转移 guard（空签名 → 该题 invalid/0，整批预检查失败返回非零）。参考实现已在 `check_scoring_contract_v2.py`，改动 `evaluate.py` 需 Lead 批准。 |
| **P1** | A/B/C 三条件使用 3 个不同版本的 `run_inference.py`，严格同代码对照不成立 | §6.2 | 正式发布前用同一提交重跑三条件；冻结清单已记录漂移。 |
| **P1** | v0.1 多答案题 = 0，TA≡EM，"语义等价多顺序"评分路径未被真实数据验证 | §2、§3(a) | v0.2 QA 必须构造并复核 ≥1 个多答案样例（不可由模型成绩反推）；v0.2 冻结前用 `audit_qa_validity.py` 做 gate：若多答案仍为 0，说明语义等价样例未进入题集。 |
| **P1** | 70 题来自 7 个相关 episode，题级独立假设会高估证据 | §4.1 | 全部区间按 episode 分组 bootstrap；direction×L 仅作诊断；不把开发集 CI 外推到 test。 |
| **P1** | 文本先验（0.7714）高于去图模型 C（0.7286），A 的高分中约 0.77 可由文本解释 | §5 | 对外报告同时列 A/C/文本先验三列；forward 组才是视觉证据；inverse 组不作为视觉能力证据。 |
| **P2** | `evaluation/baseline_*/report.json` 为旧评分器构建，缺 `invalid_reasons`/`transitions_total` 字段 | §2.1 注 | 保留原文件；引用时以本轮重算为准；未来重算会自然补齐字段（数值不变）。 |
| **P2** | `docs/WBW/evidence/audit_trial_20261024.py` 与当前 `evaluate.py` 不兼容（引用已移除的 `result["skipped"]`；summary 严格相等比较会因新增字段失败），不能原地复跑 | 代码对照 | 保留为历史证据；可复跑的排列枚举/机会期望部分已由 `audit_qa_validity.py` 取代（并修正了跨版本字段比较）。 |
| **P2** | `full_v1/run_config.json` 缺 `image_condition` 字段（执行结果文档 §9.7 已记录） | 冻结清单 | v0.2 起把 `image_condition` 纳入 run_config 并参与哈希。 |
| **P2** | `data/usim_enact/_protocol/` 被 `ENACT/.gitignore` 第 19 行忽略（`/data/usim_enact/*`） | `git check-ignore` | 若证据需要随仓库版本化，需 Lead 决定加 `!data/usim_enact/_protocol/` 例外或以 `git add -f` 收录；当前证据在磁盘可用但不会自动入库。 |

## 8. 复跑命令（全部已在现场执行通过）

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'

# 1) QA 有效性（排列枚举 + 精确机会水平 + 六基线回归）
& $py -m scripts.usim.audit_qa_validity
#   -> data\usim_enact\_protocol\audit_qa_validity_usim-enact-v0.1.json；exit 0

# 2) 评分契约 v2 合成测试（a–e）
& $py -m scripts.usim.check_scoring_contract_v2
#   -> data\usim_enact\_protocol\contract\check_scoring_contract_v2.json；exit 0

# 3) 统计（direction×L / episode / 任务 / bootstrap / A-B-C 配对）
& $py -m scripts.usim.report_stats `
    --condition A=full_v1 --condition B=condB_zoom --condition C=condC_text_only
#   -> data\usim_enact\_protocol\stats\report_stats_dev_ego_thinking_false_001.json/.md；exit 0
#   固定 seed 下 JSON 与 MD 字节级稳定

# 4) 文本先验基线（与条件 C 对照）
& $py -m scripts.usim.text_prior_baseline
#   -> data\usim_enact\_protocol\text_prior_baseline_usim-enact-v0.1.json；exit 0

# 5) 协议冻结：生成 + 校验 + 自测
& $py -m scripts.usim.freeze_protocol --freeze-id 20261027
& $py -m scripts.usim.freeze_protocol --verify `
    data\usim_enact\_protocol\freeze_usim-enact-v0.1_20261027.json `
    --verify-out data\usim_enact\_protocol\freeze_usim-enact-v0.1_20261027.verify.json
& $py -m scripts.usim.freeze_protocol --self-test
#   -> freeze_*.json / .verify.json；verify exit 0，self-test 5/5

# 6) v0.1 只读性检查（在仓库根执行；无 M/D 输出即原件未被改）
Set-Location 'E:\code\UW-VLM'
git status --porcelain -- ENACT/data/usim_enact/usim-enact-v0.1
```

## 9. 建议的 v0.2 评测 gate（供 Lead 排序）

1. **数据侧**：v0.2 QA 冻结 → 跑 `audit_qa_validity --data-root <v0.2>`；硬要求：0 空参考转移、参考排列全部被接受、多答案题数 > 0（否则语义等价路径仍未验证）、记录 direction×L 精确机会水平。
2. **评分侧**：把 `ScoringContractV2` 的参考转移 guard 并入评分器（或至少在报告前用 guard 批量预检查并拒绝出分），契约测试作为 CI。
3. **冻结侧**：`freeze_protocol` 生成 v0.2 输入冻结（标签/QA/图片/prompt/模型/split/seed/代码），正式推理前确认 `--verify` 0 退出；同一提交跑 A/B/C。
4. **统计侧**：用 `report_stats` 出 direction×L + episode bootstrap + 配对表，同时附文本先验基线；对外结论按 §4.4 口径撰写。

## 附录 A：证据文件

| 文件 | 大小 | 内容 |
|---|---:|---|
| `data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.1.json` | 116 KB | 70 题逐题接受集/参考签名/PA、direction×L 汇总、精确机会水平、六基线回归与存档报告对照、v0.1 交叉校验 |
| `data/usim_enact/_protocol/contract/check_scoring_contract_v2.json` | 20 KB | 契约测试 (a)–(e) 的输入场景、断言与结果；`ScoringContractV2` 参考实现输出 |
| `data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.json` | 79 KB | A/B/C 全部统计表、bootstrap 样本区间、配对计数/Δ、失败与 identity 统计、完整性校验 |
| `data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.md` | 11 KB | 同上的可读版（固定 seed 稳定输出） |
| `data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json` | 55 KB | 逐题文本排序规则/阶段/证据、EM/PA、identity 与机会、与 C 配对对照 |
| `data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json` | 159 KB | 协议冻结清单（7 组 578 文件 + 语义化配置 + 交叉校验 + payload 哈希） |
| `data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.verify.json` | 3 KB | 生成后即时校验结果（`ok=true`，payload 哈希匹配） |

环境：Windows + `C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe`（Python 3.x，cv2/numpy/pyarrow 23.0.1），无外网调用；`evaluate.py` sha `9d137a19716d59efd8aa9ddeb9166b5e2694108d575a5f002dc1b58b691568f3`。bootstrap/split seed：20261024。

## 附录 B：与既有文档的关系

- 本报告确认并强化了 [执行结果 §6](../WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md) 的三条结论：inverse 基本不测视觉、forward L4 是视觉试金石、文本天然可排序；并给出**可复跑的确定性文本基线 0.7714**（高于 C 0.7286）与 forward 组 +40pp 的净视觉增益。
- 本报告把 [复核与补充清单 §2–3] 中"应另建可审查的评分契约样例（多答案、不可交换动作、空签名拒绝）"落实为 `check_scoring_contract_v2.py` 的 5 项自动测试；把"统计口径、按 episode 分组"落实为 `report_stats.py`；把"冻结记录不足"落实为 `freeze_protocol.py` 与 v0.1 基准冻结文件。
- 仍未完成（不在本任务范围）：v0.2 标签/QA 构建与独立复核、v0.2 模型运行、思考模式对照、正式 test 冻结；这些由 Lead 协调后在冻结清单与统计工具上重跑即可。
