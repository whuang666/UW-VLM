# ENACT × USIM 现状总览与执行手册（WBR 方案 + WBW 执行记录合并）

合并日期：2026-10-24（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。

**本文把两份材料合成一份可操作的东西**：[WBR DashScope 完整实施方案](../WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md)（该做什么、验收什么）与 [WBW 试运行复核](../WBW/ENACT-USIM试运行复核与补充清单-20261024.md)、[审计证据](evidence/trial_audit_20261024.json)、[官方文档摘录](evidence/dashscope_official_docs_20261024.json)（实际是什么、证据是什么）。不再分别阅读两份原文即可判断当前该做什么。

> WBR 目录另有 `ENACT-USIM试运行后续流程方案-20261024.md`，其文件头已声明被 DashScope 版取代，仅作历史规划，本手册不采用其中任何命令。

> **2026-10-24 12:55 更新：阶段 A/C 已实施，方案 A 的真实模型结果已产出。** 代码改造、评分契约、预检、分层冒烟、全量 70 题与去图对照均已完成，结果见 [qwen3.8-max 执行结果](ENACT-USIM-qwen3.8-max-执行结果-20261024.md)。下表 §1 的 ❌ 项中，「评分分母 / 缺资产 / 严格解析 / 续跑 / 失败留痕 / 真实成绩」已转为 ✅；**独立标签复核、扩展 episode 与最终 test 仍未做**；视觉对照 A/B/C 均已完成（B 为负结果，属天花板效应）。

---

## 1. 一页状态总览

把「方案要求」与「实际状态」逐项对齐。✅ 已核实　⚠️ 部分核实　❌ 未执行

| 工作项 | WBR 要求 | 实际状态 | 证据 |
|---|---|---|---|
| 数据与帧对齐 | 可用即可，不重复下载 | ✅ 7 条 ego 视频**顺序解码 2,635 帧**，与 Parquet/meta 行数一致；28/28 关键帧逐像素等于解码帧 | `trial_audit.alignment`、`question_image_checks` |
| 产物版本可追溯 | 源码/输入哈希可定位 | ⚠️ 7 标注 + 7 raw 场景图 + 56 张图共 70 项哈希匹配；**适配器与 `scripts/usim/*` 未跟踪、未记哈希** | `artifact_hash_checks`、`enact_head` |
| 题集与题面 | ID 唯一、图可读、映射正确 | ✅ 70 个唯一 ID、56 道 L=3 / 14 道 L=4、224 次图片引用；标签区以下像素与源帧一致 | `questions`、`qa_by_type` |
| 评分链条自洽 | oracle 全对 | ✅ 6 种基线复算与已存 `report.json` 一致，`skipped=0` | `baselines` |
| 机会水平 | 不把单次随机当理论值 | ✅ 已枚举全部合法排列（见 §3），各设定精确期望与文档一致 | `uniform_permutation_exact_chance` |
| 评分分母 | 全部冻结题计入 | ❌ PA 转移加权分母排除非法/缺失项，探测得 1.0（应为 0.4） | `probes.mixed_valid_missing` |
| 缺资产处理 | 预检失败即终止 | ❌ 缺场景图时评分 0 题、静默 skip 1 题 | `probes.missing_scene_graph` |
| 严格解析 | 只接受单一数组 | ❌ 解释文本、多数组仍被接受 | `probes.strict_parser` |
| 续跑安全 | 比对配置/QA/图片哈希 | ❌ 仅查 ID，且失败记录也算 done | 源码 `run_inference.py:115-127` |
| 失败留痕 | 失败仍占分母、状态可辨 | ❌ 失败只打印计数，退出码仍 0 | 源码 `run_inference.py:144,165` |
| 独立标签复核 | 第二位复核者，28 帧 + 全部转移 | ❌ 7 份标注 `label_source` 全为 `agent_visual_review`，无第二人记录 | `label_sources` |
| 真实 VLM 成绩 | 至少一个模型完整跑通 | ❌ `predictions/` 只有 `selftest_oracle.jsonl`，`authenticated_api_called=false` | `prediction_backends` |
| 代码改造 | 阶段 A/C 的 diff 与回归 | ❌ `runner_modified=false`、`scorer_modified=false`（一行未改） | `dashscope_plan_validation` |
| 视觉对照 B/C | 同 ID 配对的裁剪/去图条件 | ✅ B 0.9286 / C 0.7286（A 0.9571），见执行结果 §6–§7 | `condB_zoom/report.json`、`condC_text_only/report.json` |
| 扩展与最终 test | 冻结协议后运行 | ❌ 未开始；现有 7 条只作开发 | — |

一句话：**数据与题集侧已可复现，评分侧有 5 个 P0 未修，模型侧一次未跑。**

---

## 2. 已确证的事实基线（可直接引用，不必重算）

| 事实 | 数值 |
|---|---|
| 规模 | 7 条 train episode、28 关键帧、21 个可见转移、70 题 |
| 题集构成 | forward L=3 28 / L=4 7；inverse L=3 28 / L=4 7 |
| 图片输入总量 | 56×3 + 14×4 = **224 张**（一轮全量），即 70 次请求 |
| oracle | EM / TA / PA 全 1.0000 |
| 已在案基线 | identity 0.4714、reverse 0.3857、random(seed 0) 0.3571、empty/malformed 0 |
| 多答案题 | **0** —— 70 题每题只有一个被 TA 接受的排列，故 TA ≡ EM |
| USIM / ENACT 版本 | USIM commit `88c3612b…`（6,840 文件、manifest 声明完整）；ENACT HEAD `87e323a9…` |

---

## 3. 机会水平：用枚举替代单次随机

答案长度只有 2 或 3，可穷举。下表为**逐题枚举全部合法排列后过 verifier 的精确期望**，已由本手册独立复算，与 WBW 复核表逐项相同：

| 设定 | 题数 | 随机 EM | 随机 TA | 随机 PA（逐题） | identity EM |
|---|---:|---:|---:|---:|---:|
| forward L=3 | 28 | 0.5000 | 0.5000 | **0.6250** | 0.6071 |
| forward L=4 | 7 | 0.1667 | 0.1667 | 0.3333 | 0.2857 |
| inverse L=3 | 28 | 0.5000 | 0.5000 | 0.5000 | 0.4643 |
| inverse L=4 | 7 | 0.1667 | 0.1667 | 0.3333 | 0.1429 |
| **加权** | 70 | **0.4333** | 0.4333 | 0.5167 | 0.4714 |

**三条读法，直接决定主表怎么写：**

1. L=3 的机会 EM 就是 0.5，forward L=3 的随机 PA 甚至高达 0.625。**L=3 的分数没有分辨力**，模型高于 0.5 不构成能力证据。
2. 真正有信号的是 L=4（1/6），但只有 14 题。**扩 L=4/L=5 的样本比调 prompt 更值。**
3. 现有 identity 总体 0.4714 已贴近加权机会 0.4333，但 forward L=3 仍 0.6071（机会 0.5）——固定顺序捷径只是被削弱，未消除。

---

## 4. 方案与官方文档之间的四处冲突（需要拍板，否则会返工）

这些不是执行细节，而是**开跑前必须定死、开跑后不能改**的项。前两处在 WBR 里没有覆盖。

### 4.1 System Message：方案固定，官方建议不设

WBR §1.3 冻结了系统提示 `You are a careful visual reasoner. Answer exactly as instructed.`；而 [官方文档摘录](evidence/dashscope_official_docs_20261024.json) 明确写着：

> 「模型配置：在非 Agent 工具调用的通用对话场景下，为保持最佳效果，**建议不设置 System Message**，可将模型角色设定、输出格式要求等指令通过 User Message 传入。」

| 选项 | 做法 | 代价 |
|---|---|---|
| A（推荐） | 不设 system，把角色与格式要求并入 user message；题干本身已含完整输出格式，改动最小 | 与「沿用现有系统提示」的既定写法不同，需在 `run_config.json` 记录 prompt 变更 |
| B | 保留 system，接受官方建议之外的做法 | 结果可能受模板差异影响，且后续难归因 |

**建议在预检前定 A 或 B，并把 `system_prompt_sha256` 记为 null（A）或实际值（B）。** 预检后再改等于换配置，必须重开 run。

### 4.2 图像不会被服务端放大

`qwen3.8-max` 的 `min_pixels` 默认与最小均为 **65,536**；USIM 题面 320×240 = **76,800** 像素，仅高出 17%。也就是说服务端**不会**做超分补细节，「夹爪 10–15 px」的问题原样进入模型。

→ 这条坐实了 WBR 阶段 F 中条件 B（局部裁剪放大）的必要性：它不是在优化，而是在补服务端不会做的事。

### 4.3 非流式超时会「返回半截」而非报错

官方说明：非流式调用最大超时不少于 300 秒，**超时后服务中断请求并返回已生成的内容，而不是报错**。WBR 设 `timeout=180`，比服务端上限短。

→ 必须把「客户端超时且拿到部分 JSON」与「`finish_reason=length` 截断」与「正常完成」区分记录，三者都不能静默当作有效答案。

### 4.4 `max_completion_tokens` 计入思维链

官方：该参数「始终限制模型完整输出（思维链 + 回答）」。首轮 `enable_thinking=false` 时 64 足够输出 `[2,1]`；但若服务端忽略该参数（预检要验），64 会在思维链阶段就被截断，返回空 content。

→ 预检判据应包含：`enable_thinking=false` 是否真的生效（看响应有无 reasoning 字段/思考 token）+ `finish_reason` 是否为 `stop`。

---

## 5. 合并后的执行顺序

把 WBR 的阶段 A–G 与 WBW 的 P0 清单按**依赖与是否阻塞**重排。关键点：**只有预检需要密钥，代码修复与标签复核都不需要。**

| 序 | 任务 | 是否需要密钥 | 依赖 | 完成判据 |
|---:|---|---|---|---|
| 1 | 保存现状：v0.1 全部产物 + 未跟踪源码的 SHA-256 清单 | 否 | — | 70 项产物哈希 + 7 个适配器/脚本哈希可查 |
| 2 | **P0 修评分**：固定分母、资产预检即失败、严格解析、重复/未知 ID | 否 | 1 | 4 个边界探测全部达标（见 §6） |
| 3 | **P0 修运行器**：`--api-url`、env 读取、`enable_thinking`、`max_completion_tokens`、`--max-attempts`、`--dry-run`、配置哈希续跑、退出码 | 否 | 1 | `--dry-run` 能发现重复后缀/缺密钥/缺图；失败 run 非零退出 |
| 4 | 独立复核 28 帧 + 21 转移（先只给模型实际输入图） | 否 | — | 复核表 + 分歧裁决；`NextTo` 定义拍板 |
| 5 | 一题四图 API 预检 | **是** | 2、3 | 4 图确实进入请求；`finish_reason`、usage、model 字段留存 |
| 6 | 分层 20 题试跑（4 组各 ≤5） | **是** | 4、5 | 每题 L 张图；失败与格式错误分列；ID 与哈希冻结 |
| 7 | 全量开发评测（70 题或复核后 N） | **是** | 6 | 固定分母 = N；失败计 0；逐题分数完整 |
| 8 | 视觉对照 A/B/C（原图 / +局部图 / 去图文本） | **是** | 7 | 同 ID 配对，按 episode 分组 |
| 9 | 扩 20–30 条独立 episode，冻结 test | **是** | 8 | 协议冻结后才构造 test |

任务 2、3、4 可**并行**，且不需要任何密钥。任务 5 之前若 system message 取舍（§4.1）未定，预检结果不可用于正式成绩。

---

## 6. 验收判据（可机械检查，不看主观印象）

| 项 | 判据 | 当前值 |
|---|---|---|
| PA 转移加权分母 | L=3 全对 + L=4 缺失 ⇒ **0.4** | ❌ 1.0 |
| 缺资产 | 返回非零、run 标失败、不产出正式成绩 | ❌ 0 题静默 skip |
| 严格解析 | `[1,2]` ok；`Explanation: [1, 2]`、`[2, 1] then [1, 2]`、`[0,1]`、`[1,1]`、`[1, ` 全部 invalid | ❌ 前两个被接受 |
| 续跑 | 换模型/换 QA 哈希/换 prompt 时拒绝恢复 | ❌ 只看 ID |
| 失败留痕 | attempted / success / invalid / failed / missing 五类计数分离 | ❌ 只有 failures 打印 |
| 预检 | 4 图进入请求、`finish_reason=stop`、usage 与响应 model 留存 | ⏳ 待执行 |
| 报告口径 | 按 direction×L 给出 N、合法排列数、失败/缺失/格式错误、EM、TA、两种 PA，并与 identity 及 §3 随机期望并列 | ⏳ 待实现 |

---

## 7. 待你确认的两件事

1. **`VLM_API_KEY`**：当前 shell 里 `VLM_API_URL` / `VLM_MODEL_NAME` / `VLM_API_KEY` 三个都未设置，`authenticated_api_called=false`。任务 5 及之后全部卡在这里。
2. **System Message 取舍（§4.1）**：选 A（不设 system，指令并入 user，推荐）还是 B（保留现系统提示）。这决定预检的 prompt 哈希，定了就不能改。

---

## 8. 材料索引

| 文件 | 作用 |
|---|---|
| `../WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md` | 当前唯一执行依据（阶段 A–G） |
| `../WBR/ENACT-USIM试运行后续流程方案-20261024.md` | 历史稿，已被取代 |
| `ENACT-USIM试运行复核与补充清单-20261024.md` | 5 个 P0 与标签缺口的具体证据与最低验收条件 |
| `ENACT-USIM复现结果-v0.1.md` | 试点结果（含已被纠正的「100/100 未入箱」外推，以复核清单为准） |
| `ENACT-USIM-API方案重写记录-20261024.md` | 方案重写说明与未执行项 |
| `evidence/trial_audit_20261024.json` | 只读审计：对齐、哈希、基线复算、排列枚举、3 个评分探测 |
| `evidence/audit_trial_20261024.py` | 上述审计的可重跑脚本 |
| `evidence/dashscope_official_docs_20261024.json` | 官方文档摘录与响应哈希（§4 冲突的来源） |
| `evidence/dashscope_plan_validation_20261024.json` | 方案校验：产物未变、未调 API、代码未改 |
