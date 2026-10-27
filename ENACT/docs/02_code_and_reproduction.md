# 代码结构、实际契约与复现问题

最近更新：2026-10-27（Asia/Shanghai）。

> **状态（2026-10-27）**：本文是（历史，2026-10-23 代码审阅记录）；开头“下面的改动项尚未实施”与 §7“尚未验证”已过时：适配层与 `scripts/usim/*` 已实现并在 v0.1/v0.2 使用（[07 §1](07_reproduction_run.md)）；评分已升级 `usim_strict_v0.3`（固定分母、严格解析、空签名 gate，[契约证据](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)、[评分契约 §3/§10](WBW/ENACT-USIM-评分契约与统计-20261027.md)）；`qwen3.8-max` 真实模型 A/B/C 已于 2026-10-24 跑通（[执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)）。本文记录的上游 seed 重置、解析容错等缺陷仍有效，v0.1 用后处理重排与严格评分器规避。

核验版本：`87e323a985418f7dcb09e9f62d065a9d010ce98b`。源代码符号位置见 [code_index.json](evidence/code_index.json)，运行探针见 [code_smoke.json](evidence/code_smoke.json)。本轮保留上游核心实现，下面的改动项尚未实施（历史，2026-10-23；改动项已实施，见文首状态框）。

## 1. 项目包含什么

```text
scripts/enact/cli.py                  统一入口：segment / qa / eval / download
enact/processors/segmentation_processor.py  批量读取活动目录并保存关键帧
enact/core/segmentation.py            按场景图变化选帧
enact/processors/qa_gen_processor.py  遍历活动、方向和 L=3…10
enact/core/qa_generation.py           加载 TaskData，调度生成器，写 JSONL
enact/core/forward_world_modeling.py  前向 DAG、DP、采样、图片标号和排列答案
enact/core/inverse_world_modeling.py  逆向动作描述、打乱和排列答案
enact/utils/scene_graph_utils.py      场景图重建、差分、可见性与瞬态过滤
enact/utils/state_change_translator.py 谓词差分到文本/签名
enact/utils/qa_prompt_template.py     两个方向的文本模板
enact/core/evaluators.py              答案解析、语义验证、逐题评分和汇总
enact/processors/evaluator_processor.py  批量预测文件评测与输出
scripts/helpers/                     下载、仿真重放、视频分帧等工具
BEHAVIOR-1K/                         可选子模块，当前未初始化
```

本地没有发现通用 VLM 推理 runner、训练入口、人工 Gradio 标注界面、完整消融实验驱动或论文所有错误类别的统计脚本。论文 p.14 的“完整复现”声明比这个本地 checkout 提供的内容更广；需要自行补齐或核实是否有其他发布分支。

## 2. 三个主要命令实际要求什么

| 命令 | 必需输入 | 实际输出 |
|---|---|---|
| `enact segment` | 每条轨迹的 `scene_graph_0.json` 与 `external_sensor1/*.png` | 关键帧图片与 `segmented_scene_graph_0.json` |
| `enact qa` | 分帧场景图、原始场景图、原始数字帧名 PNG | QA JSONL；标号图片另存到原始数据父级的 `QA/images/` |
| `enact eval` | 预测 JSONL、分帧场景图、原始场景图 | meta 汇总、逐题结果、可选签名 |

**关键事实：评测器也要场景图。** `OrderingEvaluator._create_task_data()` 同时检查 segmented 和 raw 两份 JSON。`--analyze-wrong-cases` 只控制额外签名输出，不会取消评分时对场景图的依赖。仅按 README 下载 QA 图片和 JSONL，不能保证本地语义评测可运行。

缺少场景图时，当前代码可能打印“Evaluation aborted”，随后外层仍写空报告并显示成功。必须核对 `count`，不能只看退出码或“success”。

## 3. 中间目录

```text
data/
  replayed_activities/<episode_key>/
    scene_graph_0.json
    external_sensor1/00000.png ...
  segmented_activities/<episode_key>/
    segmented_scene_graph_0.json
    external_sensor1/<keyframe>.png
  QA/
    enact_ordering.jsonl
    images/<qa_type>/<episode_key>/*.png
```

上游把“task_name”同时当作轨迹目录名。迁移后应写成如 `usim_train_episode_000123` 的**全局唯一 episode key**，不能只写 `Pick up the pipe`。两个数据 split 的 episode 数字会重用，必须加 split 前缀。

`images` 路径以 `data/` 为根，例如 `QA/images/...png`。单独更改输出 JSONL 的位置不会自动改变图片输出目录。`key_frame_ids` 保存的是正确时间顺序，而前向 `images[1:]` 是打乱顺序；推理器禁止把 `key_frame_ids`、`gt_answer`、时间戳或文件名中的真实顺序发送给模型。

## 4. 论文、README 与实现差异

| 项目 | 论文/说明 | 本地实现与影响 | 迁移处理 |
|---|---|---|---|
| 关键帧相似度 | p.23：变化签名余弦阈值 0.97 | `segmentation.py`：比较场景图状态特征，阈值 0.98 | 记录两种算法差异，不只换一个数字 |
| 时间参数 | p.23：30 Hz 下至少 40 帧约 1.3 秒 | 分帧还有 `TEMPORAL_THRESHOLD=200`、候选延迟 10/40 帧；reader 瞬态窗口为 10 | 用秒配置并按 USIM 10 Hz 换算，在训练/验证数据定参数 |
| 短轨迹 | 输入长度无明确 README 限制 | 跳过最初 10 帧，再访问剩余序列第 50 帧；短于约 60 帧会越界 | 增加长度检查或替换分帧模块 |
| 随机种子 | CLI 提供 `--seed` | manager 使用参数，但两个 generator 初始化和 `generate()` 又重置为 42 | 用局部 RNG；非 42 种子目前不能按 CLI 承诺生效 |
| 大样本采样 | 可配置采样数 | 逆向 `generate()` 默认 `max_qa_num=25`，前向无同样上限 | 明确双向数量上限，逐层报告实际保留数量 |
| 多实例物体 | 可见物体中同类实例 | reader 会过滤涉及多个同 category 对象的差分 | 红/蓝干扰物实验需稳定实例 ID 和自然语言指代 |
| 可见性阈值 | 保证视觉可验证 | 按像素占全图百分比计算，阈值 `0.005` 是 **0.005%**，不是 0.5% | 320×240 下仅超过约 3.84 像素便通过面积条件，不能代替可辨认性审查 |
| 全部输入图 | README 泛称“未来图打乱” | 只有前向图打乱；逆向图按时间顺序 | 推理器分方向封装 |
| type 名称 | README 示例含 `..._ordering_3_steps` | generator 实际输出 `forward_world_modeling_3_steps` / `inverse_world_modeling_3_steps` | 以实际生成值为准，不硬编码 README 示例路径 |
| 总体 PA | 论文：微平均 | `report_overall_score()` 对逐题 PA 使用 `np.mean` | 固定长度报告，并区分逐题均值和转移加权汇总 |
| TA | README 部分措辞称 exact | `exact_match OR semantic_match` | 同时报告 EM、语义 TA |
| 下载入口 | `enact download` | 统一 CLI 中仍是占位打印 | 使用 helper 或固定 revision 的正式下载器 |
| 数据仓库 | README 顶部 MLL-Lab | helper 硬编码 `Inevitablevalor/ENACT`，README 也混有该链接 | 核实实际来源、版本和哈希后下载 |
| 重跑 QA | 可能被理解为续跑 | `BatchQAProcessor.run()` 会先删除已有输出 JSONL | 每次新 run 目录，禁止把它当恢复断点工具 |

`_has_added_object()` 对 dict 使用 `hasattr(..., 'parent')`，其分支不能正常按 JSON 字段识别新增对象；这也是候选延迟行为需要单独审查的原因。大规模关键帧时还需检查 DP 的 `np.int64` 计数溢出；这是扩展时的实现风险，未在本轮小样本触发。

## 5. 答案解析与分母问题

上游 `_parse_answer_string()` 会寻找最后一个数字列表、裁掉过长答案的前部、把零起始索引平移到 1 起始，还会把最小值大于 1 的列表整体平移。直接传 list 和传 string 的处理还不相同。

合成探针实际得到：

| 原始输出 | 预期答案长度 | 解析结果 |
|---|---:|---|
| 字符串 `[2, 3]` | 2 | `[1, 2]` |
| 字符串 `[0, 1]` | 2 | `[1, 2]` |
| 字符串 `[9, 2, 1]` | 2 | `[2, 1]` |
| 字符串 `[1, 1]` | 2 | `[1, 1]`，解析层未拒绝重复 |
| list `[0, 1]` | 2 | 原样返回 `[0, 1]` |
| `no answer` | 2 | `None`，后续评测跳过该题 |

迁移版应保留兼容原评测的结果，同时额外报告严格格式有效率。正式测试的分母应固定在冻结题集上，缺失、错误或超时不能因为被跳过而提高准确率。若更换了解析和计分行为，要升级 `protocol_version`，不能继续称与上游口径完全一致。

跨长度汇总探针：两题分别 `L=3, PA=1` 和 `L=10, PA=0`，上游总体 PA 为 0.5；按 `L−1` 个转移加权为 `2/11≈0.1818`。这只是口径验证的合成例子，不能当作任何模型成绩。

## 6. 复现的两个层级

**原版结果核对（可选，但建议先做小样本）：** 使用冻结的官方 QA、原始/分帧场景图和指定模型快照，复现一小部分 `L=3/4` 的评分，验证推理与 scorer。完整 8,972 题与数十模型的复现成本较高，不是开始水下迁移的前置条件。

**USIM 方法迁移（当前目标）：** 保留双向任务和状态差分语义，重建数据标签、相机映射、关键帧和推理器。数值不需要与原论文相同；应该报告新的数据范围和协议。若只做时间排序或低层控制排序，需要另命名任务，不能写成完整 ENACT 语义复现。

## 7. 本轮已验证与尚未验证

已在当前 Python 3.13 环境直接导入本地模块，用三帧合成场景各生成 1 道前向和逆向题。两者标准答案 TA/PA 均为 1，反向排列 TA 均为 0，生成图片路径均存在；另外复现了缺少场景图时评测 0 行且不抛异常的行为。

未安装 BEHAVIOR-1K/OmniGibson，未运行仿真重放、原版数据完整分帧（历史，2026-10-23）；真实模型推理与 USIM 语义评测已于 2026-10-24 完成（[执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)、[07 §6](07_reproduction_run.md)）。Python 3.13 的合成检查通过，不代表全部上游和模型依赖已兼容；推荐单建 Python 3.10 环境运行正式复现（实际运行统一使用 `C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe`，见 [07 §8](07_reproduction_run.md)；未按此建 conda 环境）。
