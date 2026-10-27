# USIM–ENACT 复现记录（v0.1 试点）

执行日期：2026-10-23。目标：在本地 `E:\code\UW-VLM\usim` 上跑通 ENACT 的数据构建与评测闭环，产出可复核的双向排序题集与基线成绩。协议版本 `usim-enact-v0.1`。

结论先行：**闭环已跑通并可自洽复验**（参考答案 EM/TA/PA 全为 1.0，随机/恒等基线落回机会水平）。**规模是试点级**：7 条 episode、28 个关键帧、21 个可见转移、70 道题。**尚未接入真实 VLM**：本机无 torch/transformers，也没有可用的多图模型服务，推理器已实现但只跑了自测后端。

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

1. **分辨率是主要瓶颈。** 320×240 下圆柱约 10–15 px，“夹爪张开悬在物体上方”和“夹爪闭合握住物体”在图上看非常接近。本轮用夹爪关节信号帮忙定边界，但模型只看到图——这批题对 VLM 偏难，而且部分题面证据不足。建议下一版对夹爪—物体区域裁剪放大，或在 Stonefish 侧提高出图分辨率。
2. **`transfer` 任务的示范不完整。** 100 条 train episode 全部以“物体仍被举在箱口”结束，无法验证 `Inside`。要覆盖“放入箱内”，需要重新采一段末端释放并等待稳定 >1 s 的轨迹。
3. **没有真实模型成绩。** 本机无 torch/transformers、无 ollama，8 GB 笔记本 GPU 也不足以稳妥跑 3B 级多图模型。`run_inference.py` 已实现 OpenAI 兼容后端（vLLM/SGLang/Ollama 均可），接上服务即可出分。
4. **`NextTo` 的判定带主观性**（“一个物体直径以内”）。首版接受这一点，但复核时应记录分歧；`docs/04` 建议的独立复核尚未执行。
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

## 9. 下一步（按性价比排序）

1. 接一个真实多图 VLM，先跑这 70 题（约 20–50 题一轮即可判断题目是否成立），确认模型不是靠“恒等/固定顺序”过关。
2. 对夹爪—物体区域做裁剪放大版题面，比较两种分辨率下的 TA，直接检验“证据不足”假设。
3. 再标注 5–10 条 episode 到 L=5（每条需要找出第 4 个语义变化，例如“抓取后先悬停再抬升”），把 L=3 的 0.5 机会水平稀释掉。
4. 若能拿到 Stonefish 场景导出（物体位姿 / 接触 / 分割掩码），把 `InGripper`/`Inside` 从人工判断换成仿真真值，并顺带解决 `target_pos` 语义问题。
