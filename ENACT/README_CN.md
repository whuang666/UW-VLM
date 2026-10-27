# ENACT 复现与水下数据迁移

最近更新：2026-10-27（Asia/Shanghai）。中文项目文档入口：[docs/README.md](docs/README.md)。

本项目把 ENACT 的前向/逆向世界建模评测迁移到当前工作区的 USIM 水下仿真数据。论文阅读、代码结构、数据核验、改造方案、实施清单与评测协议文档均已整理。

**当前状态（2026-10-27）**：USIM 数据已补齐并逐文件哈希核验；v0.1 协议已实现并冻结（7 条 episode / 70 题），评分升级为 `usim_strict_v0.3`；`qwen3.8-max` 真实模型开发集 A/B/C 三条件已跑（70 题，原图 EM 0.9571 / 局部放大 0.9286 / 去图 0.7286，70/70 请求成功）；独立标签复核 round2 已完成并修正 7 处 `OnSeabed` 语义、2 处可见性等问题。**v0.2 标注/题集构建与正式测试冻结进行中。** 详见 [docs/README.md](docs/README.md)。

请先阅读 [下一步工作清单](docs/05_next_steps.md) 与 [本地数据核验](docs/03_usim_data_audit.md)。上游原始说明仍在 [README.md](README.md)。
