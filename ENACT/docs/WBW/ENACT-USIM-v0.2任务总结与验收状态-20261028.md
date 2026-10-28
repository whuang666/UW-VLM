# ENACT × USIM v0.2 任务总结与验收状态

日期：2026-10-28（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。

本文把 v0.2 阶段的交付与结论收敛成一份可验收的清单，覆盖：数据扩展 → 题集与评分协议 → B 条件构建 → 协议冻结 → 四条件真实运行 → 统计口径。**本轮不新增实验**，只做整理、核对与两处统计口径修正。

前序文档（不重复其内容）：[v0.2 构建与协议准备](ENACT-USIM-v0.2构建与协议准备-20261027.md)（数据/题集/B 条件/冻结）、[v0.2 协议证据](ENACT-USIM-v0.2协议证据-20261027.md)（各 gate 证据）、[v0.2 开发矩阵复核与下一步](ENACT-USIM-v0.2开发矩阵复核与下一步-20261027.md)（首轮结果的独立复核与预算诊断建议）。

## 1. 一句话状态

v0.2 的数据、120 题题集、评分协议 `usim_strict_v0.3`、B 条件与协议冻结均已完成；**A/B/C/D 四条件已在 dev 上跑完（294 次请求）**；**尚未产生 val 与正式 test 成绩**，test 预留 10 条中 2 条已完成标注并通过结构／源帧检查。

## 2. 交付清单

| 项目 | 关键产物 | 证据 | 状态 |
|---|---|---|---|
| 数据与标注 | 27 条 episode、110 关键帧、83 转移（81 可见） | `usim-enact-v0.2/annotations/` | ✅ 完成（单标注者 + Lead 抽检） |
| 题集 | curated 120 题（forward/inverse 各 L3 27 / L4 30 / L5 3） | `QA/train/enact_ordering_curated.jsonl` | ✅ oracle 1.0、多答案 0、空参考转移 0 |
| 评分协议 | `usim_strict_v0.3`（空/不可见参考转移 gate） | `check_scoring_contract.py` all_pass | ✅ v0.1 A/B/C 回归逐位不变 |
| 条件 B（局部放大） | 120 题 / **432 图**（R1 246、R2 186） | `QA/conditions/B_zoom/` + `check_condition_b.py` | ✅ `status=pass`，左 panel 432/432 与 A 逐字节一致 |
| 协议冻结 | `freeze_usim-enact-v0.2_20261027b`：13 组 **1818 文件** | `_protocol/freeze_…20261027b.json` | ✅ `--verify` 0、self-test 7/7 |
| 四条件驱动 | `scripts/usim/run_v02_matrix.py`（同源同参、源码 sha 入 manifest） | `_protocol/derived/matrix_manifest_run.json` | ✅ 实跑 4 条件，failures 为空 |
| 四条件结果 | A/B/C/D dev 预测 + 报告 + 配对统计 | `runs/qwen3.8-max/v02_dev_001/`、`_protocol/stats_v0.2/model_dev/` | ✅ 已出（见 §3） |
| test 预留标注 | `001078`、`001650` 两条 | `_expansion/annotation_work/test_reserve/` | ⚠️ **2/10** |
| 正式 test | — | — | ❌ 未开始（依赖 §8） |

## 3. 四条件结果（dev，84 题 / 19 episode）

模型请求名与返回名均为 `qwen3.8-max`；`enable_thinking=false`、temperature=0、输出预算 256 tokens。

| 条件 | N | 严格合法 | invalid | EM | PA_item | PA_micro |
|---|---:|---:|---:|---:|---:|---:|
| A 原图 | 84 | 84 | 0 | **0.9286** | 0.9504 | 0.9495 |
| B 原图＋局部放大 | 84 | 75 | **9** | 0.8452 | 0.8690 | 0.8486 |
| C 去图（纯文本） | 84 | 84 | 0 | 0.5952 | 0.6359 | 0.6009 |
| D 去动作文本（仅 forward） | 42 | 42 | 0 | 0.6905 | 0.7183 | 0.6881 |

### 3.1 direction × L（EM）

| setting | N | A | B | C | D |
|---|---:|---:|---:|---:|---:|
| forward_L3 | 19 | 0.8947 | 0.8947 | 0.4737 | 0.8421 |
| forward_L4 | 21 | **0.8095** | 0.5714 | 0.1905 | 0.6190 |
| forward_L5 | 2 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| inverse_L3 | 19 | 1.0000 | 1.0000 | 1.0000 | — |
| inverse_L4 | 21 | 1.0000 | 1.0000 | 0.8571 | — |
| inverse_L5 | 2 | 1.0000 | 1.0000 | 0.0000 | — |

### 3.2 同 ID 配对（episode bootstrap，2000 次，95% CI）

| 比较 | common | both_correct | only_first | only_second | ΔEM [CI] |
|---|---:|---:|---:|---:|---|
| A − B | 84 | 70 | 8 | 1 | +0.0834 [+0.0270, +0.1354] |
| A − C | 84 | 47 | 31 | 3 | +0.3334 [+0.1771, +0.4674] |
| A − D | 42 | 26 | 10 | 3 | +0.1666 [+0.0218, +0.3172] |
| B − D | 42 | 25 | 4 | 4 | +0.0000 [−0.1136, +0.1212] |
| C − D | 42 | 11 | 2 | 18 | −0.3810 [−0.5814, −0.1795] |

A 与 D 必须在**共同的 42 道 forward 题**上比：**A 0.8571（36/42） vs D 0.6905（29/42）**，差 16.67 个百分点。D 的全量口径（42 题）与 A 的全量口径（84 题）不可直接相减，因为 A 的 84 题里含 42 道 inverse——那 42 道对 A 近乎全对、且对 D 不存在。

### 3.3 程序文本基线分层（基线答对 / 基线答错）

| 条件 | 基线答对 (N=55) | 基线答错 (N=29) |
|---|---:|---:|
| A | 0.9818 | **0.8276** |
| B | 1.0000 | 0.5517 |
| C | 0.8364 | **0.1379** |
| D | 1.0000 (N=13) | 0.5517 (N=29) |

D 只覆盖 forward 题，两层分母因此是 **13 / 29**，与 A/B/C 的 55 / 29 不同，不能横比绝对值。

## 4. 三条必须带进论文的结论

1. **inverse 方向不构成视觉证据。** 程序文本基线不看图就能答对 55/84；A、B 在 inverse L3–L5 全部 1.0000，C 也有 0.8571–1.0000。视觉证据只能来自 forward L≥4、条件 D，以及「基线答错」层的配对差值。
2. **去图后不如一个正则式启发式。** C（0.5952）低于程序文本基线 text_prior（0.6583），且在「基线答错」层只有 0.1379。把 C 当作「模型的文本能力」会高估它——它连固定模板的文本线索都没用稳。
3. **A−B 的差距不能读成「局部放大损害感知」。** A−B 的 8 例差异中 **7 例是 B 侧 256 token 截断**，仅 1 例（`1318/…4db57cf9`）是真实排序错误；B 的「基线答对」层反而 **1.0000 > A 的 0.9818**，跌落全部发生在「基线答错」层。
   **但也不能反过来说「全部差异都由预算造成」**：9 条无效里只有 1 条（`1304/…ccfd8e4e`）被人工通读确认推理链正确，其余 8 条未被逐条核验；且给足预算后它们是否都能答对，本实验未测。可支持的表述只有一句——**B 的严格 EM 混杂了输出预算效应，在读作感知指标之前必须先做预算诊断。**

## 5. 输出预算混淆（诊断，非官方分数）

| 条件 | invalid | `finish_reason=length` | 说明 |
|---|---:|---:|---|
| A | 0 | 0 | 全部 `stop` |
| B | **9** | **8** | 8 条散文推理被 256 token 截断；1 条容错格式（`[1]` 长度不足） |
| C | 0 | 0 | 全部 `stop` |
| D | 0 | 0 | 全部 `stop` |

机制：B 的 640×240 宽幅复合图诱发冗长推理，256 token 预算在输出最终排列前耗尽 → 解析失败 → 按 v0.3 记 0（**评分正确，不需要也不允许事后改分**）。

边界：只有 1 条截断输出被人工通读（推理链正确、在 Action 3 处被切断），其余 7 条截断与 1 条列表长度错误**未逐条核验**，也没有做「同题加大预算后是否答对」的对照。因此本节只支持「B 的严格 EM 被预算污染」这一判断，不支持「B 真实能力与 A 相当」。

**后续实验已补上这一对照**：§13 在同一 16 题上把预算提到 1024，截断从 4 条降到 1 条，同时暴露出 2 条「答案正确但格式不合规」——即预算只能解释一部分，格式服从是另一个独立问题。

单例证据（`usim_train_episode_001304_forward_world_modeling_4_steps_ccfd8e4e`，gt `[3,2,1]`）：模型逐条给出「Action 1 → Next State 3」「Action 2 → Next State 2」，内容正确，但在输出最终列表前被截断。因此 B 的低分是**格式/预算交互**，不是感知退化；要得到可解释的 B 数字，必须在更大预算下**独立重跑**（见 §8）。

## 6. 运行元数据

| 项 | 值 |
|---|---|
| 运行目录 | `data/usim_enact/runs/qwen3.8-max/v02_dev_001/` |
| 请求数 | 294（A/B/C 各 84 + D 42），另有 1 次冒烟不计入 |
| 完成时间 | A 20:41:42 / B 20:47:06 / C 20:50:00 / D 20:52:11（2026-10-27） |
| 源码 | `run_inference.py` sha `4cfc3a5a…`、`evaluate.py` sha `f18086e0…`（四条件同一版本） |
| 解码 | thinking=false、temp=0、max_completion_tokens=256、attempts=3、timeout=180、sleep=1.0 |
| 题集哈希 | A=C=`3a1399b1…`、B=`8e8bc269…`、D=`5a908071…` |
| 密钥 | 只经环境变量 `VLM_API_KEY` 传入，未落盘；manifest 仅记 `api_key_present=true` |

## 7. 本轮（10-28）的两处口径修正

1. **分层命名改为「程序文本基线答对／答错」。** 原写法「文本可解／不可解」容易被误读为题目固有能力属性；它其实是**基线的一次行为**，随基线与模板版本变化。内部字段仍保留 `text_solvable` 以兼容既有证据，表格与文档统一用新称谓并逐行标注 N。
2. **`report_stats.py` 新增 `--allow-subset`。** 以前只要各条件 ID 集不相等就返回 exit 2（D 是 forward 子集，必然触发），导致「2 是不是失败」只能靠人记。现在显式声明子集后仍需满足：成员 ⊆ 首条件、交集上 gt 与状态数一致，才返回 0，并在 `integrity` 里记录 `declared_subset_ok`、`ids_outside_first`。本次四条件报告已按此重跑：**exit 0**，`gt_conflicts=[]`、`ids_outside_first` 全 0。同时把脚本里沿用的「70 题 / 7 episode」固定说明改为实际数量。

## 8. 未完成与下一步（按依赖排序）

1. ~~**B/A 输出预算诊断**~~ **已完成（§13），gate 未通过**：1024 token 下 B 仍有 1 条截断 + 3 条严格解析失败，其中 2 条属「答案已正确、格式不合规」。下一步不是继续加预算，而是先在 §13.2 的三条路径里定稿格式契约。
2. **格式契约定稿后再决定 294 次重跑**：选路径①则预算 1024 + 预注册 v0.4「可提取」副指标，四条件同规则重跑；选②则需新 `freeze_id`。**在契约定稿前不启动 294 次**，避免再产出一张被格式污染的表。
3. **test 剩余 8 条标注**：`1384 / 1734 / 1259 / 1273 / 1145 / 1497 / 1549 / 1378`。其中 `1384`、`1378` 是 transfer（有 open 事件），是否用 `NearBox` 记 `at_box` 需先定口径，否则 test 无 L=5 题。标注需独立复核，本轮 2 条只过了结构／源帧检查，不等于质量验收。
4. ~~**论文选图**~~ **已出稿（§12）**：三张图 + 素材自检表已交付，等排版反馈。
5. **B 图入库取舍**：432 张复合图（49 MB）与 v0.2 关键帧同口径未入库，仅由冻结清单哈希锁定。全新克隆后 `--verify` 在 images 组会报缺失，需决定是否随仓库分发。

## 9. 限制（如实记录）

1. 无 val 与 test 成绩；本文所有 EM 均为 dev 结果，不构成泛化估计。
2. v0.2 标注为单标注者 + Lead 抽检；双人一致性仅 2 条抽样证据。
3. L=5 全库仅 6 题（dev 4 题、2 条 episode），不支持长时域结论。
4. `qwen3.8-max` 为别名，返回名一致**只证明别名命中**，不证明底层快照不可变。
5. B 是数字放大（R1 2.0×、R2 1.6×），不增加高频细节；`ep1330/f00080` 4 帧目标被放大窗裁切（0.9%），方向为保守衰减。
6. dev 上的 prompt/参数选择已完成；据 test 调参被明令禁止，test 只报一次。

## 10. 复现命令

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$env:VLM_API_KEY = '<key>'      # 仅会话内；不要写文件或命令行参数

# 四条件（同源同参）；先用 --dry-run 校验输入
& $py scripts\usim\run_v02_matrix.py --dry-run
& $py scripts\usim\run_v02_matrix.py --new-run

# 统计（含基线分层；D 为 forward 子集需 --allow-subset）
& $py scripts\usim\report_stats.py --data-root data\usim_enact\usim-enact-v0.2 `
    --run-dir data\usim_enact\runs\qwen3.8-max\v02_dev_001 `
    --condition A=A_full_image --condition B=B_zoom --condition C=C_text_only --condition D=D_no_action_text `
    --text-prior data\usim_enact\_protocol\baselines_v0.2\text_prior_predictions.jsonl --allow-subset `
    --out-md data\usim_enact\_protocol\stats_v0.2\model_dev\report_stats_model_dev.md `
    --out-json data\usim_enact\_protocol\stats_v0.2\model_dev\report_stats_model_dev.json

# 冻结复核
& $py scripts\usim\freeze_protocol.py --verify data\usim_enact\_protocol\freeze_usim-enact-v0.2_20261027b.json
```

## 11. 材料索引
| 路径 | 内容 |
|---|---|
| `runs/qwen3.8-max/v02_dev_001/{A_full_image,B_zoom,C_text_only,D_no_action_text}/` | 预测、响应、attempts、run_config、report、report.items |
| `_protocol/stats_v0.2/model_dev/report_stats_model_dev.{json,md}` | 四条件总表、direction×L、episode bootstrap、全组合配对、基线分层、integrity |
| `_protocol/derived/matrix_manifest_run.json` | 四条件题集哈希、源码 sha、解码参数、failures |
| `_protocol/freeze_usim-enact-v0.2_20261027b.json` | 13 组 1818 文件冻结（payload `6d14fb83…`） |
| `_protocol/condition_b_check_usim-enact-v0.2.json` | B 条件独立校验（`status=pass`） |
| `_expansion/annotation_work/test_reserve/` | test 标注 spec 与成品（2 条） |

## 12. 论文配图（2026-10-28 出稿）

生成脚本 `scripts/usim/make_paper_figures.py`（只读素材，不改任何证据）。全部白底、不透明 RGB、300 dpi。

| 成品 | 文件（`docs/WBW/figures/`） | 素材 | 说明 |
|---|---|---|---|
| 主文图 1 任务示意 | `fig1_task_overview.png` | ③ 干净关键帧 + ① 题面图 | 上半 (a) 为 5 个干净状态按真实时序排列（s0→s4）；下半 (b) 为同一题的 5 张带标签输入 + 逐字动作列表 + 输出约束 + 该题 gt `[4,1,2,3]` |
| 主文图 2 A/B 对比 | `fig2_condition_AB.png` | ①② 同题同状态 | 两行（state index 0 / 2）× 两列（A / B），B 右半放大面板用橙框标出，图注注明 1.6–2.0× 数字放大、未新增传感器信息 |
| 附录图 截断案例 | `fig3_appendix_truncation.png` | ② + `predictions.jsonl` | B 输入、原始回答前 34 行、`max_completion_tokens=256`、`completion_tokens=256`、`finish_reason=length`、`parsed=None → 0`；标为单例开发诊断 |
| 素材对照（自检） | `source_vs_rendered.png` | 原件 + 渲染后 | 证明渲染唯一变换是 LANCZOS 重采样：无修图、无改色、无内容裁切 |

选材：图 1 用 `001304` 的 L=5 题 `…827185aa`（gt `[4,1,2,3]`，避免"照顺序答"的误读）；图 2 用 `…d7fd42e4`（gt `[3,1,2]`）；附录用 `…ccfd8e4e`（即被截断那条，gt `[3,2,1]`）。三题互不重复，读者不会把示意题与诊断题混淆。

**未制作**："局部放大损害感知"的结论图——证据不支持（见 §4 第 3 条）。

## 13. 1024-token A/B 配对诊断（2026-10-28 实跑，gate 未通过）

固定 16 题（forward L3/L4/L5 = 4/4/2，inverse L3/L4/L5 = 2/2/2，seed 20261028）× A/B = **32 次逻辑请求**，输出预算 1024，其余解码参数与原 run 一致（thinking=false、temp=0、attempts=3、timeout=180）。运行目录 `runs/qwen3.8-max/v02_budget1024_diag_v1/`，`plan_sha256=3193f2eb…`，耗时 2 分 39 秒，`state=complete`、`budget_gate=fail_on_fixed_subset`（exit 3）。

| 条件 | N | answered | 缺失/失败 | `finish_reason` | 截断 | 严格合法 | 合法率 | gate |
|---|---:|---:|---:|---|---:|---:|---:|---|
| A | 16 | 16 | 0 / 0 | stop 16 | 0 | 16 | **100%** | ✅ |
| B | 16 | 16 | 0 / 0 | stop 15, **length 1** | 1 (6.25%) | 13 | **81.25%** | ❌ |

同一 16 题在历史 256 预算下的对照（`historical_256`）：A 仍 100%；B 为 `length 4`（25%）、严格合法 12/16（75%）。

### 13.1 关键发现：失败模式被预算"转换"了，但没有消失

| 预算 | B 的无效数 | `length` 截断 | `extra_text`（格式） | 其中**结尾已有合法列表** |
|---|---:|---:|---:|---:|
| 256（同 16 题） | 4 | 4 | 4（与截断重合） | 0 |
| 1024（同 16 题） | 3 | 1 | 3 | **2** |
| 256（全 84 题，历史） | 9 | 8 | 8 | 0 |

- 256 → 1024 把截断从 4 条压到 1 条，说明**预算确实不够**，加大有效；
- 但 1024 下剩下的 3 条里有 **2 条是 `stop` 正常结束、且结尾已输出正确列表**（`…45a760d1` 结尾 `[3, 2, 1]`、`…827185aa` 结尾 `[4, 1, 2, 3]`，后者与 gt 一致），只因前面写了推理散文而被 v0.3 判 `extra_text`；
- 剩下 1 条（`…cda525ee`）到 1024 仍在推理中途被截断。

**结论：预算不是唯一原因。** 即使把预算继续加大，最多只能消掉那 1 条截断，另外 2 条**在任何预算下都不会通过**严格解析——它们不是"想不出答案"，而是"答案对了但没按格式只说列表"。这与 A 形成鲜明对照：A 的 `completion_tokens` 观察最大值只有 **13**，即 A 从不触发啰嗦；宽幅复合图 B 诱发的冗长推理是条件特异现象。

### 13.2 因此 gate 判定为不通过，且不建议直接按 1024 跑 294 次

按预注册判据（只看零截断 / 零缺失 / 严格合法率 100%，**不看 EM**），B 的两项都不达标。若此时以 1024 跑统一四条件，B 仍带 3/16 的格式性 0 分，产出表依旧无法区分"感知"与"格式"。

三条可选路径（需在 test 前定稿，且必须对**所有条件**同规则生效、可追溯）：

| 方案 | 做法 | 代价 | 风险 |
|---|---|---|---|
| **① 保持 v0.3 主指标，另报"可提取"副指标** | 新增 v0.4：允许"散文 + 结尾单个合法列表"被提取；主指标仍 v0.3 | 低（只改分析层，A/C/D 不受影响） | 副指标须在 test 前预注册，否则像为 B 松绑 |
| ② 加强格式约束后重跑 | 如 assistant 前缀预填 `[`、或在题干再加硬约束 | 中（属 prompt 变更，四条件全重跑） | 改变协议，需新 freeze_id |
| ③ 接受格式失败为被测行为 | 不修，B 的格式不合规本身作为结论报告 | 零 | 论文只能说"B 更易不合规"，不能说感知差异 |

**我的建议**：①，且立即预注册——因为研究问题是感知而非格式服从；同时把预算定在 1024（截断已降到 1/16）。但**在路径定稿前不启动 294 次**，避免产出第二张仍被格式污染的表。
