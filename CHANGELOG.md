# 项目变更摘要

只记录有实质影响的变化。逐日检查命令、结果与推送状态见 [docs/daily/](docs/daily/README.md)。

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
