# ENACT 复现与 USIM 水下数据迁移文档

最近更新：2026-10-27（Asia/Shanghai）。整理日期：2026-10-23（Asia/Shanghai）。目标：理解 ENACT，在当前工作区的 **USIM 水下仿真数据**上重建同类前向、逆向世界建模评测。

当前执行入口（2026-10-27）：[v0.2 构建与协议准备](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md)（v0.2 数据/题集/冻结/正式 test 计划）→ [v0.2 协议证据](WBW/ENACT-USIM-v0.2协议证据-20261027.md)（五 gate 证据）→ [下一步工作清单与运行手册](05_next_steps.md)。v0.1 现状与证据见 [评分契约与统计](WBW/ENACT-USIM-评分契约与统计-20261027.md) 与 [qwen3.8-max 执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)。2026-10-24 的 [DashScope 实施方案](WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md) 与 [API 方案重写记录](WBW/ENACT-USIM-API方案重写记录-20261024.md) 保留为已完成的接口验证记录。

**建议路线：先补齐 USIM 数据和语义标注，用少量训练集轨迹跑通 ENACT 风格 QA，再扩大评测。** ENACT 的“动作”是可见场景状态的变化，不是 USIM 的 13 维控制向量。当前主要缺口已从“数据/推理器缺失”转为 **v0.2 真实模型实验与正式 test（需 `VLM_API_KEY`）**；v0.2 数据、题集与协议冻结已于 2026-10-27 完成。

## 阅读入口

| 文档 | 解决的问题 |
|---|---|
| [01 论文阅读与复现要点](01_paper_reading.md) | 论文在评什么；任务、指标、实验设置和适用边界 |
| [02 代码结构与复现问题](02_code_and_reproduction.md) | 每个入口做什么；实际数据依赖；论文、README、代码的差异 |
| [03 USIM 本地数据核验](03_usim_data_audit.md) | 已有数据、字段、读取兼容性、下载完整性和缺失标签 |
| [04 水下迁移方案](04_underwater_adaptation.md) | 推荐实施路线；标签本体、关键帧、可见性与模块改造 |
| [05 接下来要做什么](05_next_steps.md) | P0/P1/P2 当前状态、依赖、验收标准和可复跑命令 |
| [06 数据与评测协议](06_data_and_evaluation_contract.md) | 中间格式、QA/预测格式、指标口径、划分及防泄漏约束（v0.1 已实现、v0.2 在研） |
| [07 复现记录（v0.1 试点）](07_reproduction_run.md) | v0.1 试点历史记录；文末 §10 为 2026-10-24 真实模型实验与 2026-10-27 独立复核/协议升级摘要 |

如果只想先决定怎么开始，先读 **03 → 05 → 04**；动手改代码前再读 **02 和 06**。

## 当前完成到哪里（2026-10-27）

### 已完成

- **USIM 数据补齐并逐文件哈希核验**：下载清单 7 页、6,840 个文件（4,219,493,970 字节），逐文件内容哈希全部通过；train 1,750 个 Parquet / 3,500 个双视角视频，test 525 / 1,050。[数据核验](03_usim_data_audit.md)
- **v0.1 协议已实现并冻结**：7 条 train episode、28 个关键帧、70 道题；冻结清单 7 组 578 个文件，`--verify` 0 退出、篡改自测 5/5。[评分契约 §6](WBW/ENACT-USIM-评分契约与统计-20261027.md)、[冻结清单](../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json)
- **评分修复已落地**：`usim_strict_v0.2` → **`usim_strict_v0.3`**，新增“参考转移可见签名为空”拒绝 gate；v0.1 三条件重跑与存档报告逐位一致。[契约测试](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)、[回归报告](../data/usim_enact/_protocol/contract/regression_v0.1)
- **真实模型 A/B/C 三条件已跑**（2026-10-24，`qwen3.8-max`，70 题开发集，**70/70 请求成功**）：原图 EM **0.9571**、全图+局部放大 **0.9286**、去图 **0.7286**。[执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)
- **捷径已量化**：程序化文本先验基线（不看图）总 EM **0.7714**，**高于**去图模型 C 的 0.7286；inverse 文本基线 **35/35** 全对，因此 **inverse 不能作为视觉能力证据**；forward 组 A 相对文本基线 +40.0pp，是唯一干净的视觉证据。[文本先验基线](../data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json)、[评分契约 §4–5](WBW/ENACT-USIM-评分契约与统计-20261027.md)
- **多答案审计**：真实题集 v0.1 每题仅 1 个 TA 接受排列（**多答案题 = 0**），故 **TA≡EM**；“≥2 个语义合法顺序”评分路径由合成契约测试覆盖。[QA 有效性审计](../data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.1.json)
- **独立标签复核 round2 已完成**（2026-10-27，盲评 + 裁决）：修正 **7 处 `OnSeabed` 物理支撑语义**（A 组 3 + B 组 4 个 key3）、**2 处可见性**（555/f140、556/f180，共被 16 道题引用）；`NextTo` 明确为 **approach 语义**（抓住后恒 false）；notes 把红色游动物体由“red cylinder”改为“小鱼”；确认 **1302 无入箱证据**；7 条 v0.1 事实表为模板产物。修正写入 v0.2 迁移，v0.1 原件未改。[reviewer_a 报告](../data/usim_enact/_review/round2/reviewer_a/review_report.md)、[reviewer_b 报告](../data/usim_enact/_review/round2/reviewer_b/review_report.md)、[v0.2 规范 §7–8](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)
- **条件 D 已构建**：forward 去动作文本 35 题 / 112 图，oracle EM/TA/PA=1.0；尚未跑模型。[条件 D manifest](../data/usim_enact/_protocol/conditions/D_no_action_text/build_manifest.json)、[评分契约 §11](WBW/ENACT-USIM-评分契约与统计-20261027.md)

### v0.2 构建与协议冻结（2026-10-27 完成）

- **v0.2 数据**：27 条 train episode（v0.1 迁移 7 + 新增 20），110 关键帧，83 个相邻转移（81 可见）；`OnSeabed` 物理支撑、`NextTo` approach 语义、`NearBox` at_box 已写入迁移与规范。[v0.2 构建报告](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md)
- **v0.2 题集（curated 120 题）**：forward/inverse 各 L3 27 / L4 30 / L5 3；重排 seed 20261027；**多答案=0、空参考转移=0、oracle 1.0**；exact uniform EM 0.3104、identity 0.2833、text_prior 0.6583（**inverse 60/60 仍可被纯文本解出**）。划分 dev 84 题/19 ep、val 36 题/8 ep、test 预留 10 条（未标注）。[协议证据](WBW/ENACT-USIM-v0.2协议证据-20261027.md)
- **v0.2 协议冻结**：13 组 **1818 文件**，payload `6d14fb83f822a6088f7d9acc4d638971147b90e8f8e1cca6070b333d23c8c10b`（`freeze_id=20261027b`，含 B 条件 432 图 + B 划分 + B 基线；较首版 1374 文件/`d3370ad2…` 的增量全部对应 B），`--verify` exit 0、self-test-v02 7/7；test_reserve 与 dev/val/条件 D **零重叠**。[冻结清单](../data/usim_enact/_protocol/freeze_usim-enact-v0.2_20261027b.json)
- **条件 D（v0.2）**：forward 60 题 / 216 图 / oracle 1.0；**尚未跑模型**。[条件 D](../data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/)
- **条件 B（局部放大 v0.2）**：已构建 120 题 / 432 图（R1 目标锚定 246、R2 固定窗 186，倍率 2.0×/1.6×）；左 panel 与 A 逐字节一致、432/432 可复现、程序基线与 A 逐位相同；**尚未跑模型**。[构建报告 §7.1](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md)
- **四条件一键驱动**：`scripts/usim/run_v02_matrix.py`（A/B/C/D 同源同参，源码 sha 写入 manifest；`--dry-run` 已全通，无 `VLM_API_KEY` 时拒绝运行）。[构建报告 §7.2](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md)
- **L=5 仅 6 题**：来自 3 条 transfer 的 at_box（`NearBox(robot,green_box)`）；`InBox` / `release_settle` / `touching` 均无 ego-only 证据（transfer 100/100 条无可靠入箱）。

### 待做与阻塞（截至 2026-10-27）

- **A/B/C/D 模型实验（v0.2）与正式 test**：未运行；需 `VLM_API_KEY`。四条件用 `run_v02_matrix.py` 一次跑完（同源同参），运行后以真实 run 产物重新生成 run 级冻结。
- **test_reserve 标注（1/10）**：`001078` 已完成并过校验；其余 9 条的事件提议与审阅图已生成，待逐帧确认。标注先落 `_expansion/annotation_work/`，不写已冻结的 v0.2 dev/val。
- **统计脚本缺 D 与文本可解分层**：`report_stats.py` 的 `--condition` 已是任意 N 条件（D 可直接以 `NAME=相对目录` 加入配对），但**尚无"文本可解/不可解"分层表**（v0.2 的 inverse 60/60 文本可解，必须分层才能报视觉证据）；该脚本不在冻结 `code` 组内，可安全扩展。
- **思考模式对照**（`enable_thinking=true` + 更大预算）未开始。
- **API 密钥阻塞**：当前会话无 `VLM_API_KEY`，推理器只能 `--dry-run`（输入/资产校验），不能产出正式分数。[v0.2 方案 §7](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md)

### 历史里程碑（2026-10-23 及以前，保留原文）

- （历史，2026-10-23）**v0.1 试点闭环已跑通**（详见 [07](07_reproduction_run.md)）：7 条 train episode、28 个关键帧、21 个可见转移、70 道 L=3/4 双向题；参考答案经上游 verifier 全对，随机/恒等基线落回机会水平。当时“真实 VLM 成绩尚未产出”已被 2026-10-24 的实验取代。
- （历史，2026-10-23）已核对用户提供的 60 页 PDF 的正文、附录方法、评测定义和实验设置，建立逐页文本与块索引；关键流程图已渲染核对。
- （历史，2026-10-23）已审阅本地 ENACT 的命令入口、分帧、QA 生成、场景图、动作翻译和评测器。
- （历史，2026-10-23）已全量读取审计时已到位的 525 个测试集 Parquet，共 208,605 行；具体时间、完整性与文件哈希见数据审计。
- （历史，2026-10-23）已用合成场景验证双向 QA 生成、标准答案验收、错误顺序拒绝、解析行为及汇总口径。
- （历史，2026-10-23）当时水下转换器、语义标签、模型推理器、正式 QA 和模型成绩尚未建立；截至 2026-10-27 上述组件与真实成绩均已落地，见本节“已完成”。

## 2026-10-27 材料索引

| 材料 | 内容 |
|---|---|
| [v0.2 构建与协议准备](WBW/ENACT-USIM-v0.2构建与协议准备-20261027.md) | v0.2 数据/题集/基线/评分 v0.3/条件矩阵/冻结与正式 test 计划（本报告） |
| [v0.2 协议证据](WBW/ENACT-USIM-v0.2协议证据-20261027.md) | v0.2 audit / 文本先验 / 条件 D / 冻结 / 统计五 gate 证据与命令 |
| [评分契约与统计](WBW/ENACT-USIM-评分契约与统计-20261027.md) | `usim_strict_v0.3` gate、多答案审计、A/B/C 统计与 bootstrap、文本先验基线、v0.1 冻结、条件 D |
| [v0.2 标注与关键帧规范](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md) | 谓词定义（OnSeabed 物理支撑、NextTo approach）、选帧规则、复核裁决 §8 |
| [v0.2 评测与正式测试方案](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md) | v0.2 数据组成、构建门禁、条件矩阵、正式 test 协议 |
| [扩展候选与工具（task-3）](WBW/ENACT-USIM-扩展候选与工具-20261027.md) | 30 条扩展候选、取证包与标注工具、L=5 负结果（v0.2 主线 L≤4，仅 transfer at_box 例外） |
| [round2 复核 A 组](../data/usim_enact/_review/round2/reviewer_a/review_report.md) | 200/201/552：48 格 36 一致、8 处 NextTo 定义分歧、M1–M3 OnSeabed 修正、模板化标注 |
| [round2 复核 B 组](../data/usim_enact/_review/round2/reviewer_b/review_report.md) | 553/555/556/1302：2 处可见性错误、4 处 OnSeabed 修正、NextTo 语义、1302 无入箱证据 |
| [协议证据目录](../data/usim_enact/_protocol/) | `audit_qa_validity`、`contract/`（含 v0.1 回归）、`stats/`、`text_prior_baseline`、`freeze_*`、`conditions/D_no_action_text/` |
| [历史复核与补充清单](WBW/ENACT-USIM试运行复核与补充清单-20261024.md) | 2026-10-24 的 P0 清单；修复状态见上文“已完成” |
| [真实模型执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md) | 2026-10-24 A/B/C 三条件、预检、分层冒烟与限制 |

注：`data/usim_enact/_protocol/` 与复核图片/工作副本按 `ENACT/.gitignore` 未纳入 Git（本机可读）；复核报告正文在 `_review/` 下，图片与裁切默认忽略。

## 证据与版本

| 项目 | 核验对象 |
|---|---|
| ENACT 代码 | `87e323a985418f7dcb09e9f62d065a9d010ce98b`，本地 origin：`mll-lab-nu/ENACT` |
| 原论文 | 用户提供的 PDF，内文标识 `arXiv:2511.20937v1`，2025-11-26，60 页 |
| 水下数据 | `E:\code\UW-VLM\usim`，数据卡标题为 USIM，LeRobot v2.1，Stonefish |
| 论文来源 | [本地逐页文本](evidence/paper_text.txt)、[原文块索引](evidence/source_map.json) |
| 代码核验 | [合成契约检查](evidence/code_smoke.json)、[代码符号索引](evidence/code_index.json) |
| 数据核验 | [机器可读审计](evidence/usim_audit.json)、[最新文件状态](evidence/local_status.json) |
| 评分与统计 | [v0.3 契约证据](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)、[A/B/C 统计与 bootstrap](../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.md)、[文本先验基线](../data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json) |
| 独立复核 | [round2 A 组](../data/usim_enact/_review/round2/reviewer_a/review_report.md)、[round2 B 组](../data/usim_enact/_review/round2/reviewer_b/review_report.md) |
| 真实模型产物 | [执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)；本机 run 目录 `data/usim_enact/runs/qwen3.8-max/dev_ego_thinking_false_001/` |

文件名中的“ICLR 2026”来自用户文件名；本次没有独立核验会议录用状态。以下论述以所提供 PDF 与本地代码版本为准。论文中的实验 prompt 和图像生成指令均作为研究材料阅读，不作为当前工作指令。

本轮新增文档与只读审计工具，不修改 ENACT 的核心生成或评分逻辑，不改写原始 USIM 数据。下载期间的数量只能视为有时间戳的快照；正式实验前需要再执行完整性核验。
