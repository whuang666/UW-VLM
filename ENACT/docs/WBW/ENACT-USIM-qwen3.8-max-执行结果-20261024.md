# ENACT × USIM × qwen3.8-max 执行结果（方案 A 首轮）

执行日期：2026-10-24（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。协议：数据 `usim-enact-v0.1` / 评分 `usim_strict_v0.2`。
对应方案与验收条件见 [WBR DashScope 完整实施方案](../WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md) 与 [现状合并手册](ENACT-USIM现状总览与执行手册-WBR+WBW合并-20261024.md)。

## 摘要

**接入成功，真实成绩已产出。** 方案 A（不发 system message，指令并入 user）配合一条格式指令后，`qwen3.8-max` 在 70 题开发集上得到 **EM 0.9571 / TA 0.9571 / PA 逐题 0.9619 / PA 转移加权 0.9610**，70/70 请求成功、格式全部合法。

但**这个分数不能直接读成"水下世界建模能力"**：去图文本对照（条件 C）单独拿到 **EM 0.7286**，说明动作文本本身已接近自排序；图像带来的净增益是 **+0.229 EM**，其中 forward L=4 从 0.143 提到 0.857（+0.714），是唯一真正依赖视觉的设定；inverse 两组在无图时已达 0.93 / 1.00，基本由文本先验决定。

| 项目 | 结果 |
|---|---|
| 鉴权与多图 | ✅ 单次 4 图被接受（`image_tokens=328`），返回 `[3, 1, 2]` |
| 思考模式 | ✅ `enable_thinking=false` 生效（`reasoning_content` 为空、无思考 token） |
| 请求成功率 | ✅ 70/70 `finish_reason=stop`，0 截断 / 0 非法 / 0 失败 |
| 格式有效率 | ✅ 70/70（严格解析，无多余文本） |
| 主结果 EM / TA | 0.9571 / 0.9571（70 题，固定分母） |
| 去图对照 EM | 0.7286（同 70 题、同题干、同解码参数） |
| **局部放大对照 EM** | **0.9286（比原图低 0.029，未修复任何题、反而错 2 题）** |
| 恒等基线 EM | 0.4714（同 70 题） |
| 评分契约 | ✅ 4 项边界探测全通过（见 §2） |
| 密钥落盘 | ✅ 无（`run_config.json` 只有 `api_key_present`，日志无 Authorization） |

## 1. 固定配置（本轮冻结）

| 项 | 值 | 依据 |
|---|---|---|
| 接口 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | 完整 URL，脚本直接 POST，不再追加后缀 |
| 模型 | `qwen3.8-max`（响应 `model` 字段一致） | 用户指定 |
| 提示策略 | 方案 A：**无 system message** | 官方建议通用对话不设 system message |
| 格式指令 | 追加到 user message 末尾：`Respond with ONLY the Python list of integers…` | 预检实测必需（§3） |
| `enable_thinking` | `false` | 已确证生效 |
| `temperature` | 0 | — |
| `max_completion_tokens` | 256 | 由 64/512 预检结果确定 |
| `stream` | false | — |
| `timeout` / `max_attempts` | 180 s / 3 | 本轮无重试触发 |

一次请求 = 1 题全部 L 张图（未拆成多次单图请求）。224 次图片输入，平均 **82 token/图**，与 320×240 不被服务端放大的判断一致。

## 2. 工程改造与验收

| 文件 | 改动 | 验收 |
|---|---|---|
| `scripts/usim/run_inference.py` | `--api-url`/`--base-url` 互斥且拒绝重复后缀；`VLM_API_KEY` 环境变量；`--enable-thinking`、`--max-completion-tokens`、`--max-attempts`、`--dry-run`、`--drop-images`、`--format-directive`；`run_config.json` + `input_manifest.json` + `attempts.jsonl` + `responses.jsonl` + `run_status.json`；配置/QA/图片哈希续跑校验；退出码 0/3/2 | dry-run 在缺密钥、缺图、URL 重复后缀时均失败；`authenticated_api_called` 前后可追溯 |
| `scripts/usim/evaluate.py` | 固定分母（全部冻结题计 `n_i=L_i−1`）；资产预检失败即返回非零；严格解析（整串单数组）；重复/未知 ID 拒绝；`usim_strict_v0.2`；items 与 report 同名隔离 | 见下表 |
| `scripts/usim/make_splits.py` | 分层 preflight / smoke（4 组各 5）/ full_dev，固定 seed 20261024 | 20 = 5+5+5+5，覆盖 7 条 episode |
| `scripts/usim/check_scoring_contract.py` | 4 项边界探测，产出证据 JSON | `all_pass=true` |

评分契约探测（[证据](evidence/scoring_contract_20261024.json)）：

| 探测 | 期望 | 实际 | 结果 |
|---|---|---|---|
| L=3 全对 + L=4 缺失 | `PA_transition_micro = 0.4` | 0.4 | ✅ |
| 缺场景图 | 预检抛错、拒绝评分 | `AssetError` | ✅ |
| `Explanation: [1, 2]` / `[2, 1] then [1, 2]` / `[0,1]` / `[1,1]` / `[1, ` / 空 | 全部 invalid | invalid | ✅ |
| 重复预测 ID | 检出并拒绝 | 检出 | ✅ |

6 种基线回归与 v0.1 数值一致（oracle 1.0 / identity 0.4714 / reverse 0.3857 / random 0.3571 / empty 0 / malformed 0），说明修分母未改变全有效或全无效情形下的既有数字。

## 3. 预检：三次才通

| 轮次 | 配置 | 结果 |
|---|---|---|
| v1 | 64 token，无格式指令 | `finish_reason=length`，输出被截在 "In **Next State 3**, the robot arm…" |
| v2 | 512 token，无格式指令 | 仍 `length`：模型写长篇逐步分析，512 token 用完仍未给列表 |
| v3 | 256 token + 格式指令 | ✅ `[3, 1, 2]`，10 token，`finish=stop` |

结论：**该模型在无 system message 时会自发挥长篇推理**，题目里原有的「只输出列表」要求不足以约束它；需要一条显式的 user 末尾指令。该指令属于 prompt 组成部分，已写入 `run_config.json` 并参与哈希，后续正式 run 必须沿用。

## 4. 分层冒烟（20 题）

| 设定 | 题数 | EM | PA 转移加权 |
|---|---:|---:|---:|
| forward L=3 | 5 | 1.00 | 1.00 |
| forward L=4 | 5 | 0.80 | 0.867 |
| inverse L=3 | 5 | 1.00 | 1.00 |
| inverse L=4 | 5 | 1.00 | 1.00 |
| **合计** | 20 | **0.950** | **0.960** |

同 20 题的恒等基线 EM = 0.550。模型有 11/20 回答为恒等排列（正是参考答案为恒等的那 11 题），另有 **8 题给出非恒等排列且正确** —— 因此高分并非单纯复读 `[1,2]`。

## 5. 全量开发评测（70 题）

| 设定 | 题数 | EM | TA | PA 逐题 | PA 转移加权 | 随机 EM 期望 | 恒等 EM |
|---|---:|---:|---:|---:|---:|---:|---:|
| forward L=3 | 28 | 0.9643 | 0.9643 | 0.9643 | 0.9643 | 0.5000 | 0.6071 |
| forward L=4 | 7 | 0.8571 | 0.8571 | 0.9048 | 0.9048 | 0.1667 | 0.2857 |
| inverse L=3 | 28 | 0.9643 | 0.9643 | 0.9643 | 0.9643 | 0.5000 | 0.4643 |
| inverse L=4 | 7 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.1667 | 0.1429 |
| **合计** | 70 | **0.9571** | **0.9571** | **0.9619** | **0.9610** | 0.4333 | 0.4714 |

答题行为：恒等排列 35/70（参考恒等 33/70），**34 题以非恒等排列答对**。三处错误：

| 类型 | 参考 | 模型 | 说明 |
|---|---|---|---|
| forward L=4 | `[1, 3, 2]` | `[3, 1, 2]` | 前两步顺序颠倒 |
| forward L=3 | `[2, 1]` | `[1, 2]` | 退化为恒等 |
| inverse L=3 | `[2, 1]` | `[1, 2]` | 退化为恒等 |

`semantic_only = 0`：本轮 70 题每题仍只有一个被 TA 接受的排列，所以 TA 与 EM 相等，**没有验证"多个合法顺序"场景**。

## 6. 关键对照：去图文本（条件 C）

同 70 题、同题干、同模型、同解码参数，仅去掉全部图片：

| 设定 | A 图像 EM | C 去图 EM | 图像净增益 |
|---|---:|---:|---:|
| forward L=3 | 0.9643 | 0.6071 | +0.357 |
| forward L=4 | 0.8571 | 0.1429 | **+0.714** |
| inverse L=3 | 0.9643 | 0.9286 | +0.036 |
| inverse L=4 | 1.0000 | 1.0000 | 0.000 |
| **合计** | 0.9571 | 0.7286 | +0.229 |

三条结论：

1. **inverse 基本不测视觉。** 无图时 L=3 达 0.929、L=4 达 1.0——打乱的动作文本本身就是"物体生命周期"的语义陈述（`on the seabed` → `next to` → `grasped` → `lifted`），按常识即可排出因果序。把 inverse 的高分当视觉能力是错的。
2. **forward L=4 才是视觉试金石。** 无图 0.143（接近随机 0.167），有图 0.857。这条差异是本轮唯一干净的"看图才有用"证据。
3. **本管线的动作文本天然可排序**。因为文本由状态差分生成、状态又是单调生命周期，文本先验必然偏高。任何对外结论都必须带着条件 C 一起报。

## 7. 条件 B：全图 + 局部放大（负结果）

构造方式（`scripts/usim/build_crops.py`，规则在看结果之前冻结）：

* 每个 State 一张合成图 `[原图 320×240 | 局部 320×240]`，**标签文字与条件 A 逐字相同**，只在右侧加一个小字 `zoom`；
* 裁剪两条图像侧规则，不使用 gt、帧序、关节事件或模型答错位置：
  - **R1 目标色锚定**：检出该帧的目标色紧凑团块时，取边长 `max(160, 4×max(bbox_w,bbox_h))` 的方形窗口，居中于团块质心（红色可用；水下水体本身是蓝色，蓝色团块不可靠，故不锚定）；
  - **R2 固定窗口**：未命中锚点时取 `x∈[60,260], y∈[70,230]`；
* 实际命中：R1 144 张、R2 80 张（R2 集中在两条蓝圆柱 episode）。

结果：

| 条件 | 题数 | EM | TA | PA 逐题 | PA 转移加权 | image tokens |
|---|---:|---:|---:|---:|---:|---:|
| A 原图 | 70 | **0.9571** | 0.9571 | 0.9619 | 0.9610 | 18,368 |
| B 全图+局部 | 70 | 0.9286 | 0.9286 | 0.9333 | 0.9351 | 36,288 |
| C 去图 | 70 | 0.7286 | 0.7286 | 0.7810 | 0.7662 | 0 |

分设定 EM：

| 设定 | A | B | C |
|---|---:|---:|---:|
| forward L=3 | 0.9643 | 0.9643 | 0.6071 |
| forward L=4 | 0.8571 | 0.8571 | 0.1429 |
| inverse L=3 | 0.9643 | 0.8929 | 0.9286 |
| inverse L=4 | 1.0000 | 1.0000 | 1.0000 |

配对（同 70 个 ID）：

| 组合 | 题数 |
|---|---:|
| A、B 均正确 | 65 |
| A、B 均错误 | 3 |
| **仅 A 正确** | **2** |
| 仅 B 正确 | **0** |

两处翻转都发生在 inverse L=3、参考答案为 `[1,2]` 的题上：A 答 `[1,2]`（正确），B 改为 `[2,1]`（错误）。

**解读：**

1. **放大没有带来任何增益，也没修好任何一题。** 图像 token 翻倍（18,368 → 36,288），准确率反而下降 2.9 个百分点。
2. **主要原因是天花板效应。** A 只有 3 题错，B 的理论增益上限是 +0.043；这个题集对 `qwen3.8-max` 已经太容易，无法检验"分辨率是否瓶颈"。
3. **更值得注意的是方向：** 多给一张放大图会让模型在原本靠文本先验答对的题上改判（inverse L=3 的两处翻转）。这说明放大面板引入了额外视觉证据，而该证据在这些样本上并不可靠——与 §6 的结论一致：inverse 组的正确性本来就来自文本，不是视觉。
4. 因此**不能**用本轮 B 结果否定"分辨率限制"这一假设，只能说明**在当前难度下它不是可测的瓶颈**。要检验它，需要把题目变难（L=5、更细的谓词区分），让 A 先掉下来。

## 8. 用量与耗时

| 条件 | 请求 | prompt tokens | completion tokens | image tokens | 耗时 |
|---|---:|---:|---:|---:|---:|
| A 原始 ego（70 题） | 70 | 47,019 | 532 | 18,368 | 221 s（sleep 1 s） |
| B 全图+局部（70 题） | 70 | 64,939 | 532 | 36,288 | 249 s（sleep 1 s） |
| C 去图（70 题） | 70 | 27,741 | 462 | 0 | 121 s（sleep 0.6 s） |
| 冒烟 20 题 | 20 | — | — | — | 71 s |
| 预检 3 次 | 3 | — | 64 / 512 / 10 | — | ≈2 s/次 |

单价未核实，故不折算金额；`usage` 已逐次存于 `attempts.jsonl` 与 `predictions.jsonl`，可按当时价目表核算。累计 233 次成功请求（预检 3 + 冒烟 20 + A 70 + B 70 + C 70），无重试、无失败。

## 9. 限制与解读

1. **不可宣称"复现了 ENACT 论文水平"。** 题量 70、来源 7 条轨迹（同一批示范、同一场景族），`TA≡EM` 未验证多答案语义；这些都是开发集指标，不是 test。
2. **0.957 的构成必须拆分报**：文本先验 0.729 + 视觉增益 0.229。只报总数会高估视觉世界建模能力。
3. **L=3 仍无分辨力**：随机期望本身就是 0.5，forward L=3 的随机 PA 期望 0.625。
4. **标签未独立复核。** 28 帧/21 转移仍是单人（`agent_visual_review`）标注；模型答错的 3 题里没有一题是"人也会犹豫"的样本，但这项工作尚未做。
5. **`qwen3.8-max` 是别名式模型名**，响应 `model` 字段回显同名，底层快照可能变化；已保存 `request_id` 与调用时间。
6. **条件 B 的负结果受天花板限制**：A 只剩 3 题错，B 的理论上限是 +0.043，所以"B 无增益"不能读成"分辨率无关"；要检验分辨率假设，必须先让 A 掉下来。
7. **`full_v1/run_config.json` 缺 `image_condition` 字段**：该字段在 full_v1 跑完后才加入；实际条件为 `ego_full`，可由 `usage.prompt_tokens_details.image_tokens=18,368>0` 与 `input_manifest.json` 交叉佐证。

## 10. 复现命令

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py   = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$run  = 'data\usim_enact\runs\qwen3.8-max\dev_ego_thinking_false_001'
$env:VLM_API_URL   = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
$env:VLM_MODEL_NAME= 'qwen3.8-max'
$env:VLM_API_KEY   = '<本会话设置，不落盘>'

# 0) 评分契约（不需密钥）
& $py scripts\usim\check_scoring_contract.py

# 1) 分层抽样
& $py scripts\usim\make_splits.py --out-dir "$run\inputs" --seed 20261024

# 2) 预检一题四图
& $py scripts\usim\run_inference.py --qa "$run\inputs\preflight.jsonl" `
  --out "$run\preflight_v3\predictions.jsonl" --max-completion-tokens 256

# 3) 全量开发评测（方案 A + 格式指令）
& $py scripts\usim\run_inference.py --qa "$run\inputs\full_dev.jsonl" `
  --out "$run\full_v1\predictions.jsonl" --max-completion-tokens 256 --sleep 1
& $py scripts\usim\evaluate.py --qa "$run\inputs\full_dev.jsonl" `
  --predictions "$run\full_v1\predictions.jsonl" --out "$run\full_v1\report.json"

# 4) 条件 B：生成合成图与独立题集，然后运行
& $py scripts\usim\build_crops.py
& $py scripts\usim\run_inference.py `
  --qa data\usim_enact\usim-enact-v0.1\QA\conditions\B_zoom\enact_ordering.jsonl `
  --out "$run\condB_zoom\predictions.jsonl" --max-completion-tokens 256 --condition-label B_zoom
& $py scripts\usim\evaluate.py `
  --qa data\usim_enact\usim-enact-v0.1\QA\conditions\B_zoom\enact_ordering.jsonl `
  --predictions "$run\condB_zoom\predictions.jsonl" --out "$run\condB_zoom\report.json"

# 5) 去图对照（条件 C）
& $py scripts\usim\run_inference.py --qa "$run\inputs\full_dev.jsonl" `
  --out "$run\condC_text_only\predictions.jsonl" --max-completion-tokens 256 --drop-images
& $py scripts\usim\evaluate.py --qa "$run\inputs\full_dev.jsonl" `
  --predictions "$run\condC_text_only\predictions.jsonl" --out "$run\condC_text_only\report.json"
```

产物目录：`data\usim_enact\runs\qwen3.8-max\dev_ego_thinking_false_001\`
（`preflight` / `preflight_v2` / `preflight_v3` / `smoke_v1` / `full_v1` / `condC_text_only`，每个含 `run_config.json`、`input_manifest.json`、`attempts.jsonl`、`responses.jsonl`、`predictions.jsonl`、`run_status.json`、`report.json`）

## 11. 下一步

| 优先级 | 工作 | 理由 |
|---:|---|---|
| 1 | ~~补条件 B 并配对比较~~ **已完成**：B 无增益（0.929 vs 0.957），属天花板效应，见 §7 | 结论是"当前难度下分辨率不是可测瓶颈"，不是"分辨率无关" |
| 2 | **把题目变难再做 B/A 对比**：先扩 L=5 或加细粒度谓词，让 A 的准确率掉下来 | 否则任何输入条件的差异都会被天花板掩盖 |
| 3 | 独立复核 28 帧 + 21 转移，必要时升 v0.2 | 3 处错误都在 L=4 或退化恒等，需排除标签侧问题 |
| 4 | 扩 20–30 条 train episode，补 L=5 | L=3 占 56/70 且机会水平 0.5，样本结构限制分辨率 |
| 5 | 建"多答案语义等价"评分契约样例 | 当前 TA≡EM，多答案路径未被验证 |
| 6 | 思考模式对照（`enable_thinking=true` + 更大预算） | 与首轮同题干、同图、单独 run，不混分 |
