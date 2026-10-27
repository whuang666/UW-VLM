# USIM–ENACT 数据与评测协议（v0.1 已实现并冻结；v0.2 在研）

最近更新：2026-10-27（Asia/Shanghai）。

> **状态（2026-10-27）**
>
> - **v0.1 已实现并冻结**：`usim-enact-v0.1`（7 episode / 28 帧 / 70 题）；冻结清单 7 组 578 个文件，`--verify` 0 退出、篡改自测 5/5 —— [冻结清单](../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json)、[评分契约 §6](WBW/ENACT-USIM-评分契约与统计-20261027.md)。
> - **评分已升级 `usim_strict_v0.3`**：新增“参考转移可见签名为空”gate（空集会让任意排列虚假 TA=1），EM/TA/PA 公式不变，v0.1 三条件重跑与存档报告逐位一致 —— [契约测试](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)、[回归报告](../data/usim_enact/_protocol/contract/regression_v0.1)。
> - **v0.2 语义变更见新规范**：`OnSeabed` 改为物理支撑语义（夹住仍贴底=true）、`NextTo` 显式 approach 语义、可见性/选帧/notes 规则与独立复核裁决 —— [v0.2 标注与关键帧规范](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)、[v0.2 评测与正式测试方案](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md)。
> - **多答案路径**：真实题集 v0.1 **多答案题 = 0**（每题仅 1 个 TA 接受排列）→ **TA≡EM**；“≥2 个语义合法顺序”由合成契约测试覆盖 —— [QA 有效性审计](../data/usim_enact/_protocol/audit_qa_validity_usim-enact-v0.1.json)。
> - **文本先验**：程序化基线（不看图）总 EM **0.7714 > 去图模型 C 0.7286**，inverse **35/35** 全对 → **inverse 不能作视觉能力证据**；对外结论必须随附条件 C 与文本基线 —— [文本先验基线](../data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json)、[评分契约 §5](WBW/ENACT-USIM-评分契约与统计-20261027.md)。
> - **代码对照**：v0.1 的 A/B/C 三条件曾用 **3 个不同版本的 `run_inference.py`**；正式对照必须同一源码版本重跑 —— [评分契约 §6.2](WBW/ENACT-USIM-评分契约与统计-20261027.md)。
> - **密钥**：无 `VLM_API_KEY` 时推理器只能 `--dry-run`，不能产出正式分数。
>
> 本文 §1–§7 主体保留 2026-10-23 的协议设计说明（历史，2026-10-23）；示例格式与约束仍适用，已实现细节以本状态框与 2026-10-27 材料为准。

推荐首版协议名 `usim-enact-v0.1`。下面示例全部为结构演示，不来自真实 USIM 标注或模型输出。

## 1. 主键和来源记录

以 `(source_split, episode_index, frame_index, camera)` 唯一标识原始观测。`episode_key` 必须含 split，例如 `usim_train_episode_000123`。同一 episode 的所有帧、长短题、方向题与视觉增强版本属于同一 split。

冻结 manifest 至少记录：USIM repo ID 和解析后的 commit、所有实际使用文件的 SHA-256、ENACT commit、适配器 commit、标签/阈值/相机配置、seed、划分清单、QA 清单与图片处理配置。若远端版本不清楚，明确标为 unknown，不用 `main` 伪装成不可变版本。

## 2. 中立标注格式

```json
{
  "protocol_version": "usim-enact-v0.1",
  "episode_key": "usim_train_episode_000123",
  "source_split": "train",
  "episode_index": 123,
  "task_index": 6,
  "scenario_id": null,
  "label_source": "human_reviewed",
  "frame_index": 13,
  "timestamp_seconds": 1.3,
  "camera": "ego",
  "objects": [
    {"object_id": "robot", "category": "robot"},
    {"object_id": "red_cylinder_01", "category": "cylinder", "color": "red"}
  ],
  "facts": [
    {
      "predicate": "Grasping",
      "arguments": ["robot", "red_cylinder_01"],
      "value": true,
      "evidence": "reviewed_video_interval",
      "evidence_frame_range": [10, 20]
    }
  ],
  "visibility": [
    {
      "object_id": "red_cylinder_01",
      "camera": "ego",
      "value": true,
      "method": "human_reviewed"
    }
  ],
  "annotation_status": "reviewed"
}
```

`value` 使用 `true/false/null` 表示真、假、未知。没有标注的事实不是 false。事件另存为 before/after frame、变化事实、可见性、来源和复核状态，避免混淆控制开始、状态变化和事件完成。

人工稀疏快照仅对已审查帧和事实有效。若 evaluator 需要任意候选帧对的状态差分，必须验证这些端点快照所涉及的事实完整性；不能依靠未标注区间自动填充出“完整真值”。

## 3. ENACT 兼容场景图

上游 raw JSON 以字符串帧号作为 key，快照包含 `type: full`、小写 `nodes` 和 `edges`；支持后续 diff 重建。建议首版对选定关键帧使用完整快照，减轻增量状态错误传播。

```json
{
  "13": {
    "type": "full",
    "nodes": [
      {"name": "robot", "category": "agent", "states": []},
      {"name": "red_cylinder_01", "category": "cylinder", "states": []}
    ],
    "edges": [
      {"from": "robot", "to": "red_cylinder_01", "states": ["Grasping"]}
    ]
  }
}
```

**这段只是状态结构示例，不能直接通过现有可见性验证。** 原 reader 要求 nodes 内有各相机的像素可见性数组；只有真实像素数据才能填写。人工布尔可见性须先实现 provider/reader 适配。原论文 Figure 7 的展示使用大写 `Edges`，代码读取小写 `edges`，实现时以代码为准。

ENACT 的闭世界差分与中立标注的 unknown 不兼容；编译器应拒绝涉及 unknown 的题目，或实现有版本标识的三值差分逻辑。不要在未证明不存在时，仅凭空边列表生成“松开物体”的动作。

## 4. QA 格式与排列映射

```json
{
  "id": "usim_train_episode_000123_forward_world_modeling_3_steps_demo",
  "type": "forward_world_modeling_3_steps",
  "task_name": "usim_train_episode_000123",
  "key_frame_ids": ["0", "13", "31"],
  "images": [
    "QA/images/demo/cur_state.png",
    "QA/images/demo/next_state_1.png",
    "QA/images/demo/next_state_2.png"
  ],
  "question": "... Actions in Order: grasp the red cylinder; place it inside the box and release it ...",
  "options": [],
  "gt_answer": [2, 1]
}
```

此例的正确时间线是 `0→13→31`；展示的未来图 1 对应帧 31，图 2 对应帧 13，所以答案为 `[2,1]`。`key_frame_ids` 永远是正确时间线，不能与打乱后的 images 逐项误配。

逆向使用时间顺序不变的 `L` 张图，打乱 `L−1` 条动作并重新给展示标签，答案指向这些动作标签。共享路径保存 `trajectory_id` 到独立元数据或扩展字段，用于分组分析，模型不接收它。

每题必须验证：ID 唯一；图数为 `L`；原图均存在；参考排列恰好覆盖 `1…L−1`；每个转移非空且可见；物体指代唯一；没有时间戳/真实帧号水印；可见信息足以支持动作描述。文件名不作为模型文本输入。

## 5. 模型输入和预测

推理器只向模型发送**题干与按 images 顺序读取的图像内容**，另加固定、记录过的系统提示。严禁自动把整条 JSON 序列化给模型，因为它包含 gt_answer 和正确 key_frame_ids。

原版设置为统一 prompt、512×512、temperature=0。USIM 原始图为 320×240；是否等比例补边或拉伸，必须显式配置。若要保持原论文处理方式，记录准确实现；不能悄悄更换裁剪/分辨率后声称只是换数据集。模型不支持 temperature=0 或存在隐藏推理参数时，如实记录后端约束。

预测文件保留原始 QA 字段，只新增 `answer`，建议为字符串：

```json
{"id":"...","type":"forward_world_modeling_3_steps","task_name":"...","key_frame_ids":["0","13","31"],"images":["..."],"question":"...","options":[],"gt_answer":[2,1],"answer":"[2, 1]"}
```

配置、延迟、错误、模型版本等运行信息放到独立 sidecar，避免改变题干或破坏与冻结输入的逐字段比对。所有原字段应与冻结 QA 相等。预测记录即使失败也保留原 ID；固定 run 目录，单写入者，恢复前检查已完成 ID、配置和哈希一致性。

## 6. 评分与报告口径

> 口径说明（2026-10-27）：下表“严格版本”名称是 2026-10-23 的设计名（历史）；当前实现为 `usim_strict_v0.3`（v0.2 只修固定分母/严格解析/资产预检，v0.3 再加空签名 gate；两者在 v0.1 上数值逐位一致）。v0.1 的历史 run 报告仍标 `usim_strict_v0.2`，见顶部状态框。

建议同时保存两个清楚命名的结果：

| 结果 | 用途 | 规则 |
|---|---|---|
| `upstream_compatible` | 了解本地原 ENACT scorer 的行为 | 保留其解析、语义验证和长度不匹配对齐行为；明确可能跳题 |
| `usim_strict_v0.1` | 新水下基准的主结果 | 固定题集分母；严格排列校验；非法、超时、缺失预测记 0 并单列原因 |

严格排列必须为长度 `n=L−1` 的整数数组，集合恰好为 `1…n`，无重复、越界、布尔值或多余文本。不要通过截断、整体平移或抽取解释中的数字来修复答案。严格版本建议非法格式的 EM/TA/PA 全为 0；这与原版的容错/对齐行为不同，不能混用名义。

有效排列的指标：

- `EM`：是否等于参考排列。
- `TA`：`EM OR semantic_accept`，全题是否满足各转移的语义约束。
- `PA_i`：`c_i/n_i`，`c_i` 是位置对齐后通过前向/逆向子集检查的转移数，`n_i=L_i−1`。
- `PA_item_mean`：逐题 `PA_i` 的均值，对应原代码普通有效长度结果的汇总方式。
- `PA_transition_micro`：`sum(c_i)/sum(n_i)`，供跨长度转移加权汇总；固定 `L` 且预测有效时与前者相同。

原文 p.27 的公式中 `L` 的用法与前文“图数 L”存在符号混用；当前代码普通情况以答案长度即 `L−1` 为分母。实现中应分别命名 `num_states`、`num_transitions`，避免继续混淆。兼容版长度不匹配时按 DP 对齐得到的分母可能为两种转移长度的最大值，若要汇总该分数须保留其真实分子和分母，不能套用普通样本公式。

空签名是重要失败模式：空集总是其他集合的子集。题集构建时必须保证参考可见转移非空，unknown 或缺标不能被编译成空签名获得虚假语义通过。

## 7. 分层、不确定性和任务有效性

主表至少按 direction×L 给出：冻结样本数、实际预测数、有效排列数、错误/缺失数、EM、TA、两种 PA 口径。另按任务、场景（确实有可靠标签时）、视角和标签来源分层。不同协议版本与不同题集不要只报一个混合总体分数。

QA 共用 episode，且同路径有两个方向；bootstrap 或配对比较应按 episode 分组重采样，保持同一组中的所有 QA 与方向。模型 A/B 和视觉条件 A/B 只对相同冻结 ID 做配对；提供未配对项和失败记录。

随机排列的 **EM** 在均匀排列下为 `1/(L−1)!`；语义 TA 的随机基线可能更高，必须经 verifier 实际计算。语义 PA 也应通过实际随机预测估计，不能拿 Kendall 排序或简单的 `1/n` 公式冒充 ENACT PA。

第一阶段不必训练模型。若以后训练，使用独立 train/dev/test；同 episode 的任何片段、打乱版本、方向对和视觉增强不跨 split。若宣称场景泛化，还需按真实场景/资产分组划分，单按 episode 不足以证明未见场景泛化。
