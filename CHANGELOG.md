# 项目变更摘要

只记录有实质影响的变化。逐日检查命令、结果与推送状态见 [docs/daily/](docs/daily/README.md)。

## 2026-10-28（前缀续写方案与独立复核）

- 选择方案A，先做单题多图 Partial Mode 兼容性冒烟，再按固定16题 × A/B、2048预算诊断；当前仅形成方案，未调用 API。执行说明明确 `partial=true`、保存原始续写、固定拼接前缀及禁止按结果修补输出。
- 逐ID纠正1024／2048“同一批三条失败”的表述：共同2条，`cda525ee`为1024独有、`ea4ca751`为2048独有；保留原始预测和分数。
- 从原 ego 视频独立目检1378的选定帧；f250尚未确认达到既有离底间隙阈值，独立验收待定，原标注不覆盖。4/10仅指形成标注并通过结构／源帧检查。

## 2026-10-28（副指标规则独立冻结）

- 确认列表后只允许空白，英文／全角句号均不容忍；1024-token 诊断仍未通过，统一预算未选定，294次重跑暂缓。
- 冻结前修复畸形方括号可被跳过、响应成功状态未校验的问题；内层直接调用 v0.3 主解析器，补充完整 QA 集、哈希及重复／未知 ID 校验。
- 独立冻结8个文件与40项相关测试清单，全量54项测试及原评分契约通过；原1818文件冻结核验通过。规则与清单位于 `ENACT/docs/protocols/`。
- 现有326条响应可提取计数不变，89个旧 run 文件哈希未变；新增带规则冻结引用的报告，继续标记事后探索，不改变原主评分或预算判据。本轮未调用模型 API。

## 2026-10-28（A/B 预算诊断准备与 Windows 凭据读取）

- 新增独立的 1024-token A/B 开发诊断入口，固定 16 题、13 条 episode、32 次逻辑请求；默认仅做离线预检，输入和源码哈希锁定，严格评分及旧 run 保持原样。
- 预算判据仅使用停止原因、完整性和严格格式合法率；记录匹配的历史 256-token 子集，当前新模型结果仍为 pending，本轮未发送 API 请求。
- 按用户要求将 `VLM_API_KEY` 保存到 Windows 当前用户的持久环境变量；诊断入口可在进程变量为空时读取用户持久值。工作区仅保存读取逻辑与指导，不含密钥。
- 增加选题、输入防覆盖、续跑边界及用户环境回退的回归检查；执行说明见 `docs/workbuddyRead/usim_v02_budget_diagnostic_zh.md`。

## 2026-10-27（v0.2 开发矩阵离线复核）

- 核实 `v02_dev_001` 四条件共 294 次 HTTP 200、无重试；重新计分精确复现 A 0.9286、B 0.8452、C 0.5952、D 0.6905，冻结的 1818 文件哈希通过。
- 明确 B 有 8 条 256-token 截断和 1 条 L=3 列表长度错误；不把其低分直接归因为感知退化。
- 修正分层解释为“程序文本基线答对／答错”；D 分母为 13/29，A/B/C 为 55/29；A/D 共同 forward 42 题 EM 为 0.8571／0.6905。
- 新增可复跑的离线审计脚本、JSON 证据及结果／下一步报告；更新根 README、ENACT 文档入口与清单。
- 确认 test 预留标注 2/10 通过结构和源帧检查，独立质量验收及最终 test 评测仍待完成。

## 2026-10-27

- 将本地 UW-VLM 工作区整理为统一仓库，保留目标仓库初始历史及 ENACT 上游历史。
- 纳入 USIM 适配代码、下载核验工具、v0.1 紧凑题集及首轮真实模型评测产物。
- 新增根 README、来源说明、忽略规则、每日维护提示词和逐日记录规范。
- 保存已有第二轮复核准备脚本和文本记录；不把进行中的复核记为已完成。

## 2026-10-27（v0.2 构建与第二轮复核）

- 新增 USIM v0.2 构建/标注工具链：annotate_episode、build_condition_d、collect_v02_annotations、curate_qa_v02、make_splits_v02、migrate_v01_to_v02。
- 重写 ENACT 管线脚本：build_episode_package（episode 证据包 + L5 路线候选 + ±10 帧稳定性检查）、freeze_protocol（usim_strict_v0.3 协议冻结，新增空参考签名/可见转移硬门）、evaluate（v0.3 评分器）、check_scoring_contract_v2（v0.3 契约 + v0.1 回归）、text_prior_baseline、build_dataset、build_qa、usim_translator。
- 纳入 USIM v0.2 文本标注集（annotations/QA/manifest，关键帧 PNG 不入库）与 qwen3.8-max/v02_dev_001 开发 run 输入/基线。
- 新增 v0.2 设计文档（标注与关键帧规范、评测与正式测试方案、构建与协议准备、扩展候选与工具）。
- 保存第二轮独立复核记录（reviewer_a/b 报告、pass3 裁决、分歧、sha256；裁剪 PNG 按 .gitignore 排除）。
- 验证：tools 单测 4/4 通过；15 个修改/新增脚本语法编译通过；评分契约检查因当前环境缺 cv2 未执行，待补跑。

## 2026-10-27（v0.2 B 条件与重新冻结）

- 新增 B 条件（局部放大）构建：直接调用冻结版 `build_crops.py`（脚本未改动），在 v0.2 curated QA 上生成 120 题 / 432 张 640×240 复合图（R1 目标锚定 246、R2 固定窗口 186），题面与 A 完全相同。
- 新增独立校验脚本 `ENACT/scripts/usim/check_condition_b.py`：从源帧重推逐帧取景决策、整图重合成、逐字节比对，并审计目标可见度；证据 `status=pass`、失败 0。
- 校验结论：左 panel 与 A 原图 432/432 逐字节一致（0 像素差）；432/432 复合图可被冻结 `compose()` 精确复现；B 题集程序基线与 A 逐位相同（oracle 1.0 / identity 0.2833 / random 0.3333）。
- 量化并如实记录两个既有事实：R1 倍率恒为 2.0×、R2 为 1.6×（`4·bbox` 项从未触发下限，规则只影响取景位置）；`ep1330/f00080` 4 帧目标被放大窗左边界裁切（占 432 张的 0.9%，方向为保守衰减）。
- 新增 B 条件 dev/val 划分（`dev_B` / `val_B` / `dev_val_B` + `splits_manifest_B.json`），题号与 episode 与 A 逐条一致（已断言）。
- 重新冻结为 `freeze_usim-enact-v0.2_20261027b`：13 组 **1818 文件**（首版 1374 + B 的 images 432 / qa 2 / inputs 4 / baselines 6），payload `6d14fb83…`，`--verify` exit 0、`--self-test-v02` 7/7。
- 文档：v0.2 构建报告新增 §7.1（B 构建与校验）、条件矩阵与 §9 命令更新、§10 新增"数字放大不增加像素信息"等 2 条限制；协议证据与 README/next_steps 同步冻结与 B 状态。

## 2026-10-28（P1 离线补评：预填只修格式，不提升答案）

- 新增 `report_prefill_pilot_accuracy.py`：对现有 32 条响应事后评分，**0 次新调用**；原预测只读（运行前后哈希一致），prefill 用**派生**评分输入（`derived/<protocol>_<cond>/predictions.jsonl`），并给 stock `evaluate.py` 喂 16 题 QA 子集以免用 120 题全量导致错误 EM。
- 结果：A 严格 14/16 → 14/16；B **12/16 → 14/16**（只预填对 2、只无预填对 0）；副指标 EM 两侧均 14/16，16 题的提取排列**逐题一致**；stock evaluator 给出相同的 0.875 / 0.75，派生链与主评分器一致。
- 结论：**B 的严格分数上升完全来自格式恢复，答案内容未变**；不能据此说预填改善了感知。
- 更正事实：2048 三条格式失败的结尾列表并非全对——`ea4ca751` 结尾 `[3,1,2]`，gt `[1,3,2]`，**合法但答错**。
- 收录本轮计划与审计材料：`docs/workbuddyRead/usim_prefill_accuracy_and_test_long_plan_zh.md`、`usim_prefill_format_diagnostic_zh.md`（后者被预填冻结清单引用，此前未入库）、`evidence/prefill_long_plan_audit_20261028.json`、`evidence/prefix_format_review_20261028.json`。
- P0（新核验器 + 负例测试 + 双协议驱动）与 588 次对照仍未启动。

## 2026-10-28（前缀续写格式诊断：gate 通过，但属协议变更）

- 新增 `run_prefill_format_diagnostic.py`：在冻结请求末尾追加 `{"role":"assistant","content":"[","partial":true}`，评分对象固定为 `"[" + raw_completion`；不改题干/图片/模型/解码。凭据从环境或用户级环境变量读取，不打印不落盘。
- 两步执行：单题冒烟（`ea4ca751`，B 的 4 张复合图，2048）→ HTTP 200、`stop`、续写 `"3, 1, 2]"` 未回显前缀、拼接后合法、`completion_tokens=9`；随后冻结请求协议 `docs/protocols/prefill2048_request.freeze.json`（`freeze_id=20261028_prefill2048`，payload `86ba9f2d…`，锁 5 个文件）→ 再跑 32 次。
- 32 次结果：A 与 B 均 **16/16 严格合法、零截断、零缺失、零前缀回显**，`strict_reasons` 全 `ok`，`budget_gate=pass_on_fixed_subset`（`em_used=false`）。
- token 对照（格式证据）：预填后 A/B 合计均 138 tokens（min 6 / 中位 9 / max 12）；无预填 2048 下 B 为 3194（max 1968）。预填把 B 的冗长彻底消除，分布与 A 一致。
- 边界写入文档：预填是**协议变更**而非"模型变好"，预填/非预填两 run 不可横向当同一分数；**准确率未评估**，且预填剥夺"先推理再作答"的机会，采用前必须在 dev 上以同协议重跑四条件比对 EM。
- 新增 `tools/verify_prefill_freeze.py`：除文件哈希外，用 32 条预测里的 `body_sha256` 从冻结的 `run_inference.py` + plan 重建请求体逐条比对 → **32/32 一致**。诊断脚本在冻结后有一次纯 CLI 改动，故脚本哈希显示 `changed`，以 body 哈希作为执行的直接证据。
- 文档：总结文档新增 §15（步骤、结果、token 对照、五条边界、下一决策点），§8 更新下一步；章节编号顺序一并修正（此前 §16/§17 被插到 §12 之前）。

## 2026-10-28（2048 预算诊断：截断归零、格式失败不动；test 标注 4/10）

- `run_v02_budget_diagnostic.py` 增加 `--budget`（默认 1024，保持旧产物可读），summary 的块名随预算生成，避免 1024/2048 结果混淆。
- 新 run `v02_budget2048_diag_v1`：同 16 题、同图片/prompt/解码，仅预算 1024→2048（`plan_sha256=1bb9f1df…`，32 请求，3 分 07 秒）。结果 `state=complete`、`budget_gate=fail_on_fixed_subset`（exit 3）。
- 预算阶梯（同 16 题）：B 的 `length` 截断 4 → 1 → **0**（256/1024/2048），严格合法12→13→13/16；2048 下16条全部 `stop`，3条 `extra_text` 结尾列表均等于 gt。后续逐ID复核更正：两轮无效数同为3但不是同一批，1024的 `cda525ee` 换成2048的 `ea4ca751`。`completion_tokens` 最大值1968/2048，余量80 token。
- 冻结副指标在 2048 上：B 可提取 **16/16**（A 亦 16/16），`EM_extractable` 双方均 14/16 = 0.8750 → 严格口径的差距在 2048 下由格式解释。**不据此宣称感知等同**（16 题、单 run、副指标非感知指标）。
- 按预注册规则：**停止增加预算**，2048 不作为统一预算；下一步转向格式约束的独立版本诊断。
- test 标注推进到 **4/10**：`1384`（close 224 / open 501）与 `1378`（close 191 / open 463）均判为 **L=5**，走 2026-10-27 批准的 `at_box = NearBox(robot,green_box)` 通道；两条的 5 个关键帧全部落在 ≥8 帧渲染保持段内，`at_box` 取 release−15。`1378` 的 lift 是最弱环节（dvl 仅 +0.099 m），已在 notes 标明为单次目视证据。
- 文档：总结文档新增 §13.3（预算阶梯与停止加预算的决定），§14.3 补 2048 行，§8 更新下一步。

## 2026-10-28（副指标 extractable_permutation_v1）

- 按用户拍板落地路径①：主指标 `usim_strict_v0.3` 不变，新增独立副指标 `extractable_permutation_v1`。
- 新增 `ENACT/scripts/usim/extractable_v1.py`：仅接受 `stop` 回答；全文唯一方括号列表且位于末尾（其后只允许空白）；内层整数/长度/排列校验与严格解析器同源；多候选/截断/缺失/失败记 0；**签名无 gt 参数**；长度取 `num_states - 1` 并断言与 `len(gt)` 一致。
- 新增只读分析脚本 `ENACT/scripts/usim/report_extractable_v1.py`，产物显式标注 `post_hoc=true`、`frozen=false`、`affects_budget_gate=false`。
- 新增 `tools/test_extractable_v1.py`（22 项）：散文+末尾列表、双列表、列表不在末尾、尾随句号、未闭合括号、截断、`finish_reason=None`、空/缺失/非字符串、长度错、浮点、布尔、重复、越界，以及**与 `USIMEvaluator.parse_strict` 在裸列表上的逐例等价**。`unittest discover -s tools` 36 项全通过。
- 只读复核现有 294+32 条响应：1024 下 B 可解析数 13/16 → **15/16**（`…45a760d1`、`…827185aa`），A 与历史四条件 A/B/C/D 完全不变。与用户侧核对一致。
- 两处结论收紧：① 1024 仍未通过预算判据（尚余 1 条截断），副指标不把 gate 改判为通过；② "另外 2 条在任何预算下都不会通过"改为"这 2 条**已保存的输出**过不了严格解析，重新请求的行为尚未测量"。
- 文档：总结文档新增 §14（规则表、实现、测试、事后结果、使用边界），§13 收紧措辞，README 同步。**294 次重跑继续暂缓**。

## 2026-10-28（1024-token A/B 预算诊断）

- 实跑固定 16 题 × A/B = 32 次逻辑请求（`runs/qwen3.8-max/v02_budget1024_diag_v1`，`plan_sha256=3193f2eb…`，2 分 39 秒，`state=complete`）。
- A：16/16 严格合法、零截断、零缺失，`completion_tokens` 观察最大值仅 13。B：严格合法 13/16（81.25%）、1 条 `length` 截断、3 条 `extra_text`，`budget_gate=fail_on_fixed_subset`（exit 3）。
- 同一 16 题 256 预算对照：B 为 `length 4`、严格合法 12/16。**256→1024 把截断从 4 压到 1，但未消除失败**：1024 下 3 条无效中有 2 条是 `stop` 正常结束、结尾已输出正确列表（`…45a760d1`、`…827185aa`），仅因前面写了推理散文被判 `extra_text`；剩 1 条仍截断。
- 结论：预算不是唯一原因，这2条已保存输出也违反严格格式；换预算重新请求的行为尚未测量。1024 尚未通过判据，294次暂缓；后续已选择 v0.3 主指标加独立可提取副指标，见当日后续记录。
- 文档：《v0.2 任务总结与验收状态-20261028》新增 §13（诊断结果、失败模式转换表、三条路径取舍），§5 补后续对照指针，§8 更新下一步。

## 2026-10-28（v0.2 任务总结与统计口径修正）

- 新增 WBW 文档《v0.2 任务总结与验收状态-20261028》：把交付清单、四条件结果、direction×L、全组合配对、基线分层、预算混淆诊断、运行元数据、限制与下一步收敛为一份可验收清单，并指向 10-27 的三份前序文档（不重复其内容）。
- 修正统计口径：分层由"文本可解／不可解"改称"程序文本基线答对／答错"（它是一次基线行为而非题目属性），表格逐行带 N；`report_stats.py` 文档头里沿用的「70 题 / 7 episode」固定说明改为实际数量。
- `report_stats.py` 新增 `--allow-subset`：显式声明「某条件是首条件的真子集」（条件 D 只有 forward 题）后，仍需成员 ⊆ 首条件、交集上 gt 与状态数一致才返回 0；`integrity` 记录 `declared_subset_ok`、`ids_outside_first`。此前四条件混跑必然 exit 2、只能靠人记"2 不算失败"。四条件报告已按此重跑，**exit 0**（`gt_conflicts=[]`、`ids_outside_first` 全 0）。
- README 与 05_next_steps 同步：A/B/C/D 首轮矩阵已完成、当前优先项改为「B/A 输出预算诊断 → 统一高预算重跑 → 预留 test 标注/验收」。

## 2026-10-27（四条件驱动与 test 首条标注）

- 新增 `ENACT/scripts/usim/run_v02_matrix.py`：一条命令跑完 A/B/C/D（同源同参、固定题集 A=84/B=84/C=84/D=42），把 `run_inference.py`/`evaluate.py` 的 sha 写进 manifest，使"同一源码版本"可外部核对；密钥只从 `VLM_API_KEY` 读取，缺失即拒绝运行。`--dry-run` 四条件全通过。
- D 条件的 dev 过滤题集落在 `_protocol/derived/`（不写冻结的 `inputs/`），避免加文件破坏 `--verify`。
- test_reserve 首条 episode `001078`（Pick up the pipe）完成标注并通过 `annotate_episode --check`：4 关键帧 / 3 转移全可见 / 0 空转移；判定依据为夹爪闭合于 199、dvl 离底高度最低点在 230 且此后单调上浮。其余 9 条事件提议与审阅图已生成。
- 修正 `_expansion/tools/annotate_spec_template.json`：grasp 帧的 `OnSeabed` 由 `false` 改为 `true`（该模板仍沿用已被第二轮复核推翻的 v0.1 模板推导"抓住 ⇒ 离底"）。
- 文档：构建报告新增 §7.2（一键驱动）与 §9 首选命令，并修复上一处插入误删的 `## 8.` 章节标题。

## 2026-10-24

- 修复严格评分与 API 运行记录，采用评分协议 `usim_strict_v0.2`。
- 完成 qwen3.8-max 分层试跑和 70 题开发评测：原图 EM 0.9571、局部放大 0.9286、去图 0.7286。
- 明确文本排序捷径与小样本限制；保留独立复核和正式 test 为后续工作。

## 2026-10-23

- 补齐 USIM 固定版本并核验 6,840 个文件。
- 跑通 7 条 episode、28 个关键帧、21 个可见转移、70 题的 v0.1 构建与本地基线闭环。
