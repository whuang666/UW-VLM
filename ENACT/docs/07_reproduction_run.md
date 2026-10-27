# USIM–ENACT 复现记录（v0.1 试点）

最近更新：2026-10-27（Asia/Shanghai）。

> **历史文档说明**：本文主体记录 2026-10-23 的 v0.1 试点状态，保留为历史；文中“尚未接入真实 VLM”“独立复核尚未执行”等表述已被后续工作取代。2026-10-24 真实模型实验与 2026-10-27 独立复核/协议升级摘要见文末 **§10**。

执行日期：2026-10-23（历史）。目标：在本地 `E:\code\UW-VLM\usim` 上跑通 ENACT 的数据构建与评测闭环，产出可复核的双向排序题集与基线成绩。协议版本 `usim-enact-v0.1`。

结论先行：**闭环已跑通并可自洽复验**（参考答案 EM/TA/PA 全为 1.0，随机/恒等基线落回机会水平）。**规模是试点级**：7 条 episode、28 个关键帧、21 个可见转移、70 道题。**（历史，2026-10-23）尚未接入真实 VLM**：当时本机无 torch/transformers，也没有可用的多图模型服务，推理器已实现但只跑了自测后端；**2026-10-24 已通过 DashScope API 接入 `qwen3.8-max` 并产出开发集成绩，见 §10**。

## 1. 本轮新增了什么

| 类别 | 文件 | 作用 |
|---|---|---|
| 适配层 | `enact/adapters/usim_reader.py` | LeRobot v2.1 读取、全局 episode key、Parquet↔视频帧对齐校验 |
| 适配层 | `enact/adapters/usim_scene_graph.py` | `SceneGraphReader` 子类，支持标注式布尔可见性（不伪造像素数） |
| 适配层 | `enact/adapters/usim_visibility.py` | 可见性记录与 provider（标注 / 掩码两种口径） |
| 适配层 | `enact/adapters/usim_annotations.py` | 中立标注 schema、三值校验、编译为 ENACT 场景图 |
| 适配层 | `enact/adapters/usim_translator.py` | 水下状态词表（OnSeabed/InGripper/Lifted/InBox） |
| 适配层 | `enact/adapters/usim_visual_prompt.py` | Windows 字体修复（上游写死 Linux 字体路径，标签会退化成 10px 位图字） |
| 流水线 | `scripts/usim/build_dataset.py` | 标注 → `replayed_activities` / `segmented_activities` + manifest |
| 流水线 | `scripts/usim/build_qa.py` | 复用上游双向生成器产出 L=3/4 题集 |
| 流水线 | `scripts/usim/reseed_answers.py` | 受控重排题面标签，消除上游 seed 相关性 |
| 流水线 | `scripts/usim/run_inference.py` | 白名单字段的多图推理器（OpenAI 兼容后端 + 自测后端，可断点续跑） |
| 流水线 | `scripts/usim/evaluate.py` | 固定分母的严格评测（EM/TA/PA 双口径）+ 合成基线 |
| 复核工具 | `scripts/usim/annotate_helper.py`、`propose_frames.py` | 候选帧提案、联系人表、颜色团块信号 |

产物目录：`data/usim_enact/usim-enact-v0.1/`

```text
manifest.json                      协议、USIM 下载清单哈希、ENACT commit、逐 episode 帧哈希
annotations/episodes/*.json        7 份人工复核标注
replayed_activities/<key>/         scene_graph_0.json + external_sensor1/NNNNN.png
segmented_activities/<key>/        关键帧场景图与图（人工关键帧路线）
QA/train/enact_ordering.jsonl      70 道题（含 build_summary.json）
QA/images/<qa_type>/<key>/*.png    带 Current/Next State 标签的题面图
predictions/、evaluation/          推理与评测输出
```

## 2. 数据范围与选帧依据

只用 **train** 划分（test 保留给最终评测，未参与任何阈值、prompt 或选帧）。候选 episode 的任务限定为 `Pick up the red cylinder`、`Pick up the blue cylinder`、`Pick up the red cylinder and transfer it to the box`。

选帧不是等间隔抽帧，而是先用**夹爪信号提案**再人工目视确认：

- `observation.state[0]` 是两档夹爪关节（张开 ≈ 0.000，闭合 ≈ 0.0149，约 3 帧斜坡）。全量 train 中 `Pick up the red cylinder` 有 16/100 条出现“先短暂闭合再张开”，`transfer` 的 100 条 episode 全部出现“闭合→末端张开”。
- 该信号可靠到可以提案，但**不能当抓取真值**（闭合 ≠ 抓住）。经验值：闭合指令比“物体真正进入夹爪”早 10–40 帧。

| episode | 任务 | 关键帧 | 语义链 |
|---|---|---|---|
| 000552 | 取红圆柱 | 120 / 249 / 284 / 364 | 海床 → 靠近 → 抓住 → 抬起 |
| 000555 | 取红圆柱 | 140 / 262 / 297 / 377 | 同上 |
| 000556 | 取红圆柱 | 180 / 304 / 339 / 419 | 同上 |
| 000553 | 取红圆柱 | 110 / 140 / 168 / 248 | 同上（短 episode） |
| 000200 | 取蓝圆柱 | 140 / 213 / 248 / 328 | 同上 |
| 000201 | 取蓝圆柱 | 199 / 244 / 279 / 357 | 同上 |
| 001302 | 搬运入箱 | 150 / 168 / 196 / 415 | 海床 → 靠近 → 抓住 → 抬起搬运 |

合计 28 个关键帧、21 个相邻转移，**21/21 在 ego 视角可见且非空**。

## 3. 标签本体与“没标什么”

首版只有 4 个谓词，全部是能在一个 320×240 ego 帧里判定的：

| 谓词 | 类型 | 语义 | 判定依据 |
|---|---|---|---|
| `OnSeabed` | 一元 | 物体静置在海床 | 物体与海床接触、未被夹爪提起 |
| `InGripper` | 一元 | 被夹爪握持 | **夹爪已闭合 + 物体确实位于两指之间** |
| `Lifted` | 一元 | 被提起离开海床 | 物体与海床之间出现可见间隙 |
| `NextTo(robot, obj)` | 二元 | 夹爪到达物体旁 | 指尖与物体距离≈一个物体直径以内 |

**刻意没有标注 `Inside` / `InBox`。** 原因有据：抽查 `transfer` 任务的末尾帧（1300、1302、1305、1313 等），物体被举到箱沿/箱口上方后视频就结束了；`1302` 的末端张开指令在 f448，但 f465 物体仍在夹爪里，从未落到箱内。把“悬在箱口”写成 `Inside` 就是造假。文档 04 §3 要求 `Inside` 必须有几何真值或可审查的视频标注，这里两条都不满足。

同理，`target_pos`（6 维）在整段 episode 里大多数帧接近 0、偶发跳变，且与关节/末端运动不同步；本轮**没有**用它推导任何 `Near/Aligned/Reached`。

## 4. 与上游的口径差异（都记在 manifest 里）

| 项 | 上游 ENACT | 本轮 v0.1 | 影响 |
|---|---|---|---|
| 可见性 | `[pixel_count, bbox…]` 且阈值 0.005% | 标注布尔值，读取器走 provider；像素数只作辅助证据 | 不伪造掩码，但依赖标注可信度 |
| 词表 | BEHAVIOR 谓词（Cooked/Open/OnTop…） | 追加 4 个水下状态；节点模板改成通顺句式 | 文本与上游不同，签名也不同，不能与 BEHAVIOR 分数混算 |
| 帧命名 | helper 从 `00001.png` 起 | 严格 `frame_index`，首帧 `00000.png` | 消除一帧偏移 |
| 标签打乱 | `generate()` 内部 `random.seed(42)`，各 episode 打乱序列高度相关 | 生成后用独立 seed 重排题面标签（前向重渲染图，逆向重排动作块） | 见 §6，恒等率由 60% 降到 47% |
| 计分 | 解析容错、长度不符做 DP 对齐、解析失败跳过 | 严格排列校验，固定分母，非法/缺失记 0 并单列原因 | 分母不再被“跳过”抬高 |

## 5. 题集构成与实际数量

| 方向 | L=3 | L=4 | 合计 |
|---|---:|---:|---:|
| Forward | 28 | 7 | 35 |
| Inverse | 28 | 7 | 35 |

每题 `L` 张图、`L−1` 个动作。每条 episode 有 4 个关键帧，L=3 有 4 条路径、L=4 有 1 条，双向合计 10 题/episode × 7 = 70。**没有用重复帧或等距帧凑数**；要扩到 100–200 题，按当前产出率再标注 3–6 条 episode 即可（约 10 题/episode）。

题面示例（forward，`key_frame_ids=[140,213,328]`，`gt=[1,2]`）：

```text
[Action 1] The robot now becomes next to the blue cylinder.
[Action 2] The blue cylinder becomes grasped by the robot. The blue cylinder is now lifted
           above the seabed. The blue cylinder is not on the seabed anymore.
           The robot stopped being next to the blue cylinder.
```

## 6. 校验与基线成绩

自洽校验（题集有效性）：把参考答案当作预测输入评测器，必须全对——否则说明场景图、签名、答案三者不一致。

| 输入 | 有效排列 | EM | TA | PA(逐题均值) | PA(转移加权) |
|---|---:|---:|---:|---:|---:|
| oracle（= 参考答案） | 70/70 | **1.0000** | 1.0000 | 1.0000 | 1.0000 |
| identity（恒定 `[1,2,…]`） | 70/70 | 0.4714 | 0.4714 | 0.5214 | 0.5130 |
| reverse | 70/70 | 0.3857 | 0.3857 | 0.5071 | 0.4805 |
| random（seed 0） | 70/70 | 0.3571 | 0.3571 | 0.4548 | 0.4416 |
| empty（空输出） | 0/70 | 0 | 0 | 0 | 0 |
| malformed（`"[1, "`） | 0/70 | 0 | 0 | 0 | 0 |

分设定看恒等捷径：

| 设定 | 题数 | identity EM | random EM |
|---|---:|---:|---:|
| forward L=3 | 28 | 0.6071 | 0.4286 |
| forward L=4 | 7 | 0.2857 | 0.2857 |
| inverse L=3 | 28 | 0.4643 | 0.3571 |
| inverse L=4 | 7 | 0.1429 | 0.4286 |

要点：**L=3 只有 2 个动作，机会水平的 EM 就是 0.5**。任何 L=3 的分数都必须对着 random 基线读，不能直接当“理解能力”。这是长度决定的算术事实，不是数据缺陷；要让主指标更有分辨力，需要更多 L=4/5 的路径（即每条 episode 标注出第 4 个语义变化）。

`reseed_answers.py` 前后对比：恒等参考答案占比 0.60 → 0.4714（理论值 0.433 = 56×0.5/70 + 14×(1/6)/70）。重排后逐题校验渲染图对应帧（槽位 1→f213、槽位 2→f328，像素差 0.0），确认标签与图没有错位。

## 7. 已知问题

1. **分辨率是主要瓶颈。**（历史，2026-10-23 的假设）320×240 下圆柱约 10–15 px，“夹爪张开悬在物体上方”和“夹爪闭合握住物体”在图上看非常接近。本轮用夹爪关节信号帮忙定边界，但模型只看到图——这批题对 VLM 偏难，而且部分题面证据不足。建议下一版对夹爪—物体区域裁剪放大，或在 Stonefish 侧提高出图分辨率。**后续（2026-10-24）**：条件 B 局部放大未获增益（0.9286 < A 0.9571），但 A 仅 3 题错、存在天花板效应，故只能说明“当前难度下分辨率不是可测瓶颈”，不能否定分辨率假设，见 §10。
2. **`transfer` 任务的示范不完整。** 100 条 train episode 全部以“物体仍被举在箱口”结束，无法验证 `Inside`。要覆盖“放入箱内”，需要重新采一段末端释放并等待稳定 >1 s 的轨迹。**（2026-10-27 复核确认：1302 释放命令 f448 后至结束仅 18 帧，无脱离/沉降/落箱画面，无入箱证据，见 §10。）**
3. **（历史，2026-10-23）没有真实模型成绩。** 当时本机无 torch/transformers、无 ollama，8 GB 笔记本 GPU 也不足以稳妥跑 3B 级多图模型。`run_inference.py` 已实现 OpenAI 兼容后端（vLLM/SGLang/Ollama 均可），接上服务即可出分。**2026-10-24 已用 DashScope API 跑通 A/B/C 三条件（70/70 成功），见 §10。**
4. **`NextTo` 的判定带主观性**（首版为“一个物体直径以内”）。首版接受这一点，但复核时应记录分歧；`docs/04` 建议的独立复核尚未执行。**（2026-10-27 独立复核已完成：`NextTo` 定义为 approach 语义并加入事件锚定窗口，见 §10 与 v0.2 规范。）**
5. **上游 `--seed` 无效问题依旧存在**（generator 内部重置 42），所以本轮用后处理重排，而不是改上游。

## 8. 复现命令（PowerShell，已验证）

```powershell
Set-Location E:\code\UW-VLM\ENACT
$py = "C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe"   # numpy 2.4.6 / pyarrow 26.0.0 / opencv 4.13.0

# 1) 帧与 Parquet 对齐核验
& $py scripts/usim/build_dataset.py --check --check-episodes 552,555,200,1302

# 2) 候选帧提案 + 联系人表（人工复核用）
& $py scripts/usim/propose_frames.py --episode 1302

# 3) 编译 ENACT 兼容目录（含图与场景图）
& $py scripts/usim/build_dataset.py --overwrite

# 4) 生成双向 L=3/4 题集
& $py scripts/usim/build_qa.py --step-lengths 3,4

# 5) 受控重排题面标签（消除 seed 相关性）
& $py scripts/usim/reseed_answers.py --seed 20261023

# 6) 自洽校验 + 基线
& $py scripts/usim/evaluate.py --synthetic oracle
& $py scripts/usim/evaluate.py --synthetic random --seed 0

# 7) 接入模型后出分（示例：本地 vLLM）
& $py scripts/usim/run_inference.py --backend openai --base-url http://127.0.0.1:8000/v1 `
    --model Qwen/Qwen2.5-VL-7B-Instruct `
    --out data/usim_enact/usim-enact-v0.1/predictions/qwen25vl7b.jsonl
& $py scripts/usim/evaluate.py --predictions data/usim_enact/usim-enact-v0.1/predictions/qwen25vl7b.jsonl
```

## 9. 下一步（2026-10-23 时的计划，保留；进度见 §10）

1. 接一个真实多图 VLM，先跑这 70 题（约 20–50 题一轮即可判断题目是否成立），确认模型不是靠“恒等/固定顺序”过关。——**已完成（2026-10-24），见 §10.1。**
2. 对夹爪—物体区域做裁剪放大版题面，比较两种分辨率下的 TA，直接检验“证据不足”假设。——**已完成（条件 B），但受天花板效应限制，无净增益，见 §10.1。**
3. 再标注 5–10 条 episode 到 L=5（每条需要找出第 4 个语义变化，例如“抓取后先悬停再抬升”），把 L=3 的 0.5 机会水平稀释掉。——**由 v0.2 推进（计划新增 dev 12 / val 8，选帧规范目标 5–6 帧以支持 L=4/5），见 §10.5。**
4. 若能拿到 Stonefish 场景导出（物体位姿 / 接触 / 分割掩码），把 `InGripper`/`Inside` 从人工判断换成仿真真值，并顺带解决 `target_pos` 语义问题。——**未开始；仍待上游导出/源码确认。**

## 10. 2026-10-24 真实模型实验 + 2026-10-27 独立复核与协议升级

本节只做摘要并给出链接，不重复执行结果全文。v0.1 总览见 [评分契约与统计（2026-10-27）](WBW/ENACT-USIM-评分契约与统计-20261027.md)。

### 10.1 真实模型开发集（2026-10-24）

`qwen3.8-max`（DashScope OpenAI 兼容接口）在 v0.1 70 题开发集完成 A/B/C 三条件，**70/70 请求成功、0 截断/0 非法/0 失败**，评分协议 `usim_strict_v0.2`：

| 条件 | 输入 | EM |
|---|---|---:|
| A 原图 | ego 全图 | **0.9571** |
| B 全图+局部放大 | 每状态 `[原图 320×240 \| 局部 320×240]` | 0.9286 |
| C 去图 | 仅题干 | 0.7286 |

- 局部放大**未带来增益**（配对：仅 A 对 2 题、仅 B 对 0 题）；A 仅 3 题错，属天花板效应，只能说明“当前难度下分辨率不是可测瓶颈”。
- 产物：`data/usim_enact/runs/qwen3.8-max/dev_ego_thinking_false_001/`。→ [执行结果](WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md)

### 10.2 捷径量化与统计（2026-10-27）

- **程序化文本先验基线（不看图）总 EM 0.7714 > 去图模型 C 的 0.7286**（54 vs 51 题正确）；**inverse 文本基线 35/35 全对** → **inverse 不能作视觉能力证据**；forward 组 A 相对文本基线 +40.0pp，是唯一干净的视觉信号。
- **v0.1 多答案题 = 0**（每题仅 1 个 TA 接受排列）→ **TA≡EM**；多答案评分路径由合成契约测试覆盖。
- 按 episode 分组 bootstrap（7 簇、2000 次、seed 20261024）：A 0.9571 [0.8714, 1.0000]、C 0.7286 [0.6714, 0.8000]，A−C ΔEM **+0.2285 [+0.1285, +0.3143]**。
→ [评分契约 §4–§5](WBW/ENACT-USIM-评分契约与统计-20261027.md)、[统计证据](../data/usim_enact/_protocol/stats/report_stats_dev_ego_thinking_false_001.md)、[文本先验基线](../data/usim_enact/_protocol/text_prior_baseline_usim-enact-v0.1.json)

### 10.3 评分升级与协议冻结（2026-10-27）

- `usim_strict_v0.2` → **`usim_strict_v0.3`**：新增“参考转移可见签名为空”gate（空集会让任意排列虚假 TA=1）；EM/TA/PA 公式不变，v0.1 三条件重跑与存档报告**逐位一致**。→ [契约证据](../data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)、[v0.1 回归报告](../data/usim_enact/_protocol/contract/regression_v0.1)
- v0.1 输入已冻结：**7 组 578 个文件**，`--verify` 0 退出、篡改自测 5/5。→ [冻结清单](../data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json)
- 条件 D（forward 去动作文本，35 题 / 112 图）已构建，oracle EM/TA/PA=1.0，**尚未跑模型**。
- **P1 遗留**：v0.1 的 A/B/C 三次 run 使用了 **3 个不同版本的 `run_inference.py`**（当前工作树另有并行 v0.2 迁移改动）；正式对照必须同一源码版本重跑，冻结清单已逐条件记录漂移。

### 10.4 独立标签复核 round2（2026-10-27）

A 组（200/201/552）+ B 组（553/555/556/1302）盲评 + 裁决，结论：v0.1 7 条 episode 的 4×4 事实表为**模板产物**，并非逐帧视觉证据；并给出修正（写入 v0.2 迁移，v0.1 原件未改）：

- **7 处 `OnSeabed` 物理支撑语义**：A 组 3 处（200/f248、201/f279、552/f284）+ B 组 4 处 key3（553/f168、555/f297、556/f339、1302/f196）标 `false` 无物理证据；抓住但仍贴底时应为 `true`（dvl 离底高度最低、上浮起点在其后）。
- **2 处可见性错误**：555/f140、556/f180 目标红圆柱完全不可见（红色像素=0），原标 `visibility=true`；这两帧共被 16 道题引用。
- **`NextTo` 语义**：显式定义为 approach（到达抓取位姿、尚未夹紧；抓住后恒 false），并采用 close−15±5 帧的事件锚定窗口；原动作文本“grasped + no longer next to”自相矛盾。
- **notes 事实**：红色游动物体是**小鱼**，不是红圆柱；蓝圆柱在 ego 中偏紫。
- **1302 无入箱证据**：释放命令 f448 后至结束仅 18 帧，无脱离/沉降/落箱画面 → v0.1 不标 `InBox` 正确，但“transfer”任务名与只测 pick-up 的题面不匹配。
- 模型 3 处错误全部在 ep200，恰好落在上述最弱转移上，不能直接读作模型能力缺口。
→ [reviewer_a 报告](../data/usim_enact/_review/round2/reviewer_a/review_report.md)、[reviewer_b 报告](../data/usim_enact/_review/round2/reviewer_b/review_report.md)、[v0.2 标注与关键帧规范](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)

### 10.5 当前状态（截至 2026-10-27）

v0.2 数据/题集/协议冻结**进行中**：v0.1 七条迁移标注已落盘（[migration_v01_to_v02.json](../data/usim_enact/usim-enact-v0.2/migration_v01_to_v02.json)）；规划 dev 19 / val 8（合计 27 条开发/验证）、test 预留 10 条（冻结后才标注）；新增 20 条标注、v0.2 题集构建与冻结待完成。

- 规范与门禁：[v0.2 标注与关键帧规范](WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md)、[v0.2 评测与正式测试方案](WBR/ENACT-USIM-v0.2评测与正式测试方案-20261027.md)。
- 无 `VLM_API_KEY` 时只能 dry-run；条件 D 实跑、思考模式对照与正式 test 待 v0.2 题集/冻结就绪。
- 当前有效命令与任务状态：[05_next_steps.md](05_next_steps.md)。
