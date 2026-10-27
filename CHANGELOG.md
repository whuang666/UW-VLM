# 项目变更摘要

只记录有实质影响的变化。逐日检查命令、结果与推送状态见 [docs/daily/](docs/daily/README.md)。

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

## 2026-10-24

- 修复严格评分与 API 运行记录，采用评分协议 `usim_strict_v0.2`。
- 完成 qwen3.8-max 分层试跑和 70 题开发评测：原图 EM 0.9571、局部放大 0.9286、去图 0.7286。
- 明确文本排序捷径与小样本限制；保留独立复核和正式 test 为后续工作。

## 2026-10-23

- 补齐 USIM 固定版本并核验 6,840 个文件。
- 跑通 7 条 episode、28 个关键帧、21 个可见转移、70 题的 v0.1 构建与本地基线闭环。
