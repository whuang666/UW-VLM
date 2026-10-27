# UW-VLM

将 [ENACT](https://github.com/mll-lab-nu/ENACT) 的前向／逆向世界建模评测迁移到 [USIM 水下仿真数据](https://huggingface.co/datasets/Vincent2025hello/usim)。目前采用多图 VLM API 推理，在本地保存预测并评分。

## 当前进展

截至 2026-10-27，已保存的首轮完整模型实验执行于 2026-10-24：

- USIM 固定版本 `88c3612bf99d10652f19ec531052a38c04f0202e`，6,840 个文件通过内容哈希核验。
- `usim-enact-v0.1` 包含 7 条 train episode、28 个关键帧、21 个可见转移和 70 道 L=3/4 双向题。
- `qwen3.8-max` 已完成四图预检、20 题分层试跑及三组 70 题开发评测。

| 输入条件 | 完全匹配 EM | 请求成功数 |
|---|---:|---:|
| 原始 ego 图像 | 0.9571 | 70/70 |
| 原图＋局部放大 | 0.9286 | 70/70 |
| 去图文本 | 0.7286 | 70/70 |

这些是开发集结果。去图条件表明文本排序先验较强；独立标签复核、扩展独立轨迹和最终 test 仍需验收。2026-10-27 已出现第二轮复核与扩展准备文件，完成状态以逐项产物为准。

## 目录与阅读入口

| 路径 | 用途 |
|---|---|
| [ENACT/](ENACT/) | 保留上游代码和 MIT 许可，新增 USIM 适配、题集构建、API 推理与评分 |
| [最新执行结果](ENACT/docs/WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md) | 首轮配置、成绩、对照与限制 |
| [总体实施方案](ENACT/docs/WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md) | 标签复核、扩展和正式测试的流程；历史状态须结合执行结果阅读 |
| [ENACT/data/usim_enact/](ENACT/data/usim_enact/) | 小规模题集、关键帧、预测、评分和复核文本记录 |
| [tools/](tools/) | USIM 分页下载、内容哈希核验和回归检查 |
| [usim/README.md](usim/README.md) | 上游数据卡；完整视频和 Parquet 另行下载 |
| [每日维护提示词](docs/workbuddyRead/daily_commit_prompt_zh.md) | 给负责每日检查、记录和推送的 agent |
| [每日记录](docs/daily/README.md) / [变更摘要](CHANGELOG.md) | 逐日执行证据与项目里程碑 |

早期文档是带日期的历史快照。判断当前状态时先看代码、冻结清单、预测、评分报告和最新执行记录，不把计划里的命令或目标当成已完成工作。

## 本地使用

Git 仓库根目录是 `E:\code\UW-VLM`，远端为 `https://github.com/whuang666/UW-VLM.git`。从其他目录克隆时，按实际路径执行：

```powershell
git clone https://github.com/whuang666/UW-VLM.git
Set-Location UW-VLM
python -m pip install -r ENACT/requirements.txt
python -m pip install "pyarrow>=23"
python -m unittest discover -s tools -p 'test_*.py' -v
Set-Location ENACT
python scripts/usim/check_scoring_contract.py
```

USIM 评分契约与已保存预测的评分可使用仓库内的小规模产物；重新抽帧或扩展样本需要下载完整 USIM，见 [下载说明](tools/README.md)。BEHAVIOR-1K 子模块用于原上游流程，USIM 评测不要求初始化它。

API 凭据仅通过 `VLM_API_KEY` 环境变量读取。`VLM_API_URL` 和 `VLM_MODEL_NAME` 配置接口与模型；配置、图片、题集改变后使用新 run，不混用旧结果。完整复现命令见执行结果文档。

## Git 保存范围与来源

仓库保存代码、项目文档、紧凑题集、关键帧、预测、评分报告、输入清单和下载核验证据。完整 USIM 视频／Parquet、模型权重、传输配置、本地 agent 状态以及复核临时拼图和裁剪缓存留在外部存储或本地，受 `.gitignore` 排除。

ENACT 上游历史已合并保留，导入起点为 `87e323a985418f7dcb09e9f62d065a9d010ce98b`。第三方代码和数据的来源、许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。文件保留原始字节，避免自动换行转换破坏已有哈希记录。
