# 下一步工作清单与运行手册

这份清单按依赖排序。**现在首先需要补数据和明确语义真值；GPU 训练不在第一步。** 数据集已经确定为当前工作区的 USIM。

## P0：先使数据与协议可信

| 状态 | 工作 | 交付物与验收标准 | 责任/所需资源 |
|---|---|---|---|
| 已完成 | 阅读论文、代码和数据结构 | 本套文档、来源索引、合成契约检查 | 本轮完成 |
| 已完成 | 已到位 test Parquet 核验 | 525 文件、208,605 行可读，结构检查通过 | 本轮完成；不代表视频或标签齐全 |
| 待做 | 补齐 USIM 下载 | 固定远端 commit、分页全清单、train 1,750/test 525；视频 3,500/1,050；逐文件大小/哈希/可读性核验 | 网络和磁盘；复用已有文件 |
| 待做 | 建立隔离环境 | Python 3.10；已验证的 Arrow 23.0.1；ENACT CLI 和数据读取可用，保存依赖锁与版本 | 本地 Conda/venv |
| 待做 | 确认动作与坐标语义 | action/state 的关节与推进器映射、单位、target_pos 的对象/坐标/有效性说明 | 上游采集源码或可信文档 |
| 待做 | 确定首版标签与标注来源 | 可判定的操作谓词、unknown 规则、ego 可见性规则、标注指南 | 人工标注；或仿真状态导出 |
| 待做 | 从 train 划开发/验证集合 | 保存 episode 清单、划分种子和哈希；test 不参与阈值、模型或 prompt 选择 | 数据脚本 |

数据下载验收以元数据和冻结 manifest 为准，数量相同仍需检查路径、大小、哈希、解码和时间对应。`tools/hf_snapshot_download.py` 的递归 API 分页需先修复/核验；不把当前不完整目录当作完整数据快照，也不直接再次覆盖已到位文件。

## P1：做一个能人工检查的小闭环

| 顺序 | 工作 | 验收条件 |
|---:|---|---|
| 1 | 从 train 挑 10–20 条操作轨迹 | 原视频、Parquet、指令/场景来源可追溯；不是从 test 挑“容易题” |
| 2 | 人工标注关键帧、关系和可见性 | 至少 2–4 种可靠变化；记录未知和分歧，独立复核覆盖每种谓词 |
| 3 | 写 USIM reader 与标签适配层 | 帧 0 与 frame_index=0 对齐；ego 映射、episode 主键、标签来源正确 |
| 4 | 编译稀疏场景图与分帧输入 | unknown 不被误当 false；没有虚构 visibility 像素数；不强行运行稠密分帧 |
| 5 | 生成 `L=3/4` 双向题 | 目标约 100–200 QA，达不到时报告实际数；每个转移可在输入图验证 |
| 6 | 验证题集与 scorer | 所有参考答案通过；非法排列拒绝；EM/TA 区分，多答案行为有审查记录 |
| 7 | 写一个模型推理器 | 模型实际收到全部图、正确标签和题干；不收到答案/帧号/时间信息 |
| 8 | 开发集运行 20–50 题 | 预测逐行保存；失败计入；中断能续跑，同一 records 文件只有一个写入者 |

如果第 2–5 步发现大量语义变化不可见或不足以形成短题，先调整数据范围/标签设计；不要直接扩模型数量或开始微调。

## P2：冻结后做正式评测

- [ ] 根据开发/验证数据确定谓词阈值、prompt、图像处理、模型快照与解码参数。
- [ ] 冻结 split、QA、标签、图片清单和协议哈希，再生成测试题。
- [ ] 在实际可支持的长度上运行前向/逆向，逐方向、逐 `L`、逐任务报告数量和成绩。
- [ ] 运行随机/固定顺序及信息移除基线，检查时间、标签、文本先验捷径。
- [ ] 保留固定分母的 EM、语义 TA、PA、格式有效率、错误/缺失率；说明 PA 汇总口径。
- [ ] 对来自同一 episode 的题进行分组不确定性分析，避免把大量相关题当独立样本。
- [ ] 复核典型错误、歧义标签和低可见性样本；测试集问题若需纠正则版本化并对全部模型重评。

## P3：有了可靠基线后再扩展

- [ ] 扩至 `L=5…10`，同时报告每类任务能支持的最大长度与有效路径数。
- [ ] 引入导航/巡检/跟随；先建立目标语义、几何和成功条件。
- [ ] 增加 wrist 或双相机条件，保留 ego-only 对照，不能混合为一个分数。
- [ ] 若能获得 Stonefish 状态/接触/可见性导出，用自动流程替代人工环节并核验一致性。
- [ ] 再考虑训练、SFT/LoRA、浑浊度/光照等控制实验；每项另有独立的验证选择与测试协议。

## 已存在、可以运行的命令

以下命令适用于 PowerShell。它们核验本地项目；不需要先装 BEHAVIOR-1K。

```powershell
Set-Location E:\code\UW-VLM\ENACT

# 不安装 package 也可从仓库根看 CLI 帮助
python -m scripts.enact.cli --help

# 只读审计本地 USIM；输出放在数据目录之外
python scripts/helpers/audit_usim_readiness.py `
  --dataset-root E:\code\UW-VLM\usim `
  --output docs/evidence/usim_audit.json
```

基础环境的 Arrow 19 会报本文记录的兼容性错误，应使用新环境，或本轮已存在的临时隔离目录运行：

```powershell
python scripts/helpers/audit_usim_readiness.py `
  --dataset-root E:\code\UW-VLM\usim `
  --output docs/evidence/usim_audit.json `
  --pyarrow-site "$env:TEMP\codex-enact-audit-20261023"
```

临时目录可能被系统清理，不将它视为正式环境交付。审计返回 JSON，必须阅读 `source_unchanged_during_scan`、`declared_asset_counts_complete` 和各检查结果；资产数量不齐、读取失败或扫描时源文件变化时退出码为 1。它不验证语义真值，也没有执行全视频解码；即使退出码为 0，也不等于已完成 ENACT 语义数据准备。重跑会更新同名审计报告，正式实验使用独立 run 目录归档。

## 建议新建的正式环境（尚未执行）

```powershell
conda create -n enact-usim python=3.10 -y
conda activate enact-usim
Set-Location E:\code\UW-VLM\ENACT
python -m pip install -e .
python -m pip install pyarrow==23.0.1
enact --help
python -m pip freeze > docs/evidence/enact_usim_environment.txt
```

模型推理所需的 torch/transformers/专用模型依赖应按选定后端单独配置，不声称以上几行已经完成 VLM 推理环境。USIM 已有视频和标注适配路线不要求安装 BEHAVIOR-1K；Stonefish 自动导出路线才需要另行解决其仿真与资产依赖。

## 只有满足输入条件后才能运行的上游命令

```powershell
# 仅适用于已编译好的 ENACT 格式输入，不可直接指向 usim/test/data
enact qa data/replayed_usim_segmented data/replayed_usim data/QA/enact_ordering.jsonl --num-to-sample 5

# predictions 需要自行编写模型 runner 生成；语义评测仍需两份场景图
enact eval data/predictions/enact_ordering_mymodel.jsonl `
  --segmented-data data/replayed_usim_segmented `
  --raw-data data/replayed_usim `
  --output-root data/evaluation/usim_pilot
```

以上两条是上游 CLI 的条件性调用示例。水下目录和 predictions 目前不存在。上游 `--seed` 被 generator 内部 42 重置的问题未修复，不能据此设计多种子实验。

## 仍需要你掌握或补充的信息

1. **语义真值来源：** 是否能取得 USIM/Stonefish 的采集源码、场景配置、物体/接触状态或可重放资产；若不能，先按人工标注路线推进。
2. **控制字段说明：** 关节、夹爪、推进器映射，以及 target_pos 的真实定义。未知信息不会靠猜测写进标签。
3. **推理资源：** 已有模型/接口或可用 GPU 与显存，以便选择首个多图 VLM。先跑通一个模型即可，不必一开始复现论文全部模型。

当前最值得投入的下一项工作是：**补齐 train 与视频，然后从训练集建立小规模、可审查的操作事件标注集。**
