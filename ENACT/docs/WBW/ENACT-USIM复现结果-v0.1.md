# ENACT × USIM 水下复现结果（协议 v0.1，试点）

执行时间：2026-10-23 至 2026-10-24　|　数据：`E:\code\UW-VLM\usim`（USIM，LeRobot v2.1）　|　代码：`E:\code\UW-VLM\ENACT`

---

## 摘要

在本地 USIM 水下仿真数据上，把 ENACT 的「前向 / 逆向世界建模排序题」完整链路跑通：**标注 → 场景图编译 → 双向 QA 生成 → 严格评测**。上游核心代码未改动，通过适配层接入。

| 项目 | 结果 | 状态 |
|---|---|---|
| 数据/视频对齐核验 | `frame_index` 0 起、行数 = 解码帧数 = meta 长度，逐 episode 通过 | ✅ |
| episode 规模 | 7 条（train 划分，test 完全保留） | ✅ |
| 关键帧 | 28 个（每条 4 个） | ✅ |
| 语义转移 | 21 个，**21/21 在 ego 视角可见且非空** | ✅ |
| 题集 | **70 题**：Forward 35 / Inverse 35（L=3 各 28、L=4 各 7） | ✅ |
| 题集自洽性 | 参考答案输入评测器：EM / TA / PA 全为 **1.0000** | ✅ |
| 机会水平基线 | 随机 0.357、恒等 0.471、逆序 0.386 | ✅ |
| 真实 VLM 成绩 | **未产出**：本机无 torch / transformers / ollama，8 GB 笔记本 GPU 不足以稳跑 3B 多图模型 | ⚠️ |
| `Inside` / `InBox` | **无法标注**：transfer 任务示范全部停在「物体举在箱口」 | ❌ |

一句话结论：**机制复现成立，规模是试点级，模型评测环节待接入。**

---

## 1. 复现的到底是什么

ENACT 评的不是机器人控制，而是「看几张第一视角图 + 一串动作描述，把顺序排对」。它把世界建模拆成两个方向：

| 方向 | 已知 | 被打乱 | 输出 |
|---|---|---|---|
| Forward | 当前图 + 正确顺序的 `L−1` 条动作 | 后 `L−1` 张图 | 图的标号排列 |
| Inverse | 按时间顺序的 `L` 张图 | `L−1` 条动作 | 动作的标号排列 |

判分不是简单比对数字：正确答案可能不唯一，评测器把预测还原成状态变化，检查它是否满足语义约束（前向要求预测隐含的变化覆盖参考变化，逆向要求所选动作是参考转移的子集）。

灌进这套机制需要三样东西——**图、场景图、动作**。USIM 只有图（ego / wrist 双路 MP4）和本体状态，场景图与语义动作全缺。本轮做的就是补这两样。

| ENACT 概念 | BEHAVIOR 原版 | USIM 本轮对应物 |
|---|---|---|
| `o_t` | 第一视角 RGB | ego 相机一帧（320×240，10 FPS） |
| `s_t` | 仿真符号场景图 | 人工复核的关键帧场景图（物体 + 生命周期状态 + 可见性） |
| `a_t` | 可见场景图差分 | 如「红圆柱被夹爪握住」→「红圆柱被提离海床」 |

---

## 2. 数据范围与选帧依据

只用 **train** 划分。test（525 episodes / 208,605 帧）不参与任何选帧、阈值或题面构造，留给最终评测。

### 2.1 夹爪信号：能提案，不能当真值

`observation.state[0]` 是两档夹爪关节：张开 ≈ 0.000，闭合 ≈ 0.0149，约 3 帧斜坡。

- `Pick up the red cylinder`：100 条 train 中有 16 条出现「短暂闭合→张开→再闭合」（先抓空再重抓）；
- `Pick up the red cylinder and transfer it to the box`：**100/100 全部出现**闭合→末端张开的完整循环。

但这个信号必须打折扣：**闭合指令比「物体真正进入夹爪」早 10–40 帧**，闭合也不代表抓住。因此它只用来缩小搜索范围，最终每个关键帧都由目视复核确定。

### 2.2 七条 episode 的语义链

| episode | 任务 | 关键帧 | 语义链 | 夹爪事件 |
|---|---|---|---|---|
| 000552 | 取红圆柱 | 120 / 249 / 284 / 364 | 海床 → 靠近 → 抓住 → 抬起 | 闭合 f264 |
| 000555 | 取红圆柱 | 140 / 262 / 297 / 377 | 同上 | 闭合 f277 |
| 000556 | 取红圆柱 | 180 / 304 / 339 / 419 | 同上 | 闭合 f319 |
| 000553 | 取红圆柱 | 110 / 140 / 168 / 248 | 同上（短 episode，263 帧） | 闭合 f148 |
| 000200 | 取蓝圆柱 | 140 / 213 / 248 / 328 | 同上 | 闭合 f228 |
| 000201 | 取蓝圆柱 | 199 / 244 / 279 / 357 | 同上 | 闭合 f259 |
| 001302 | 搬运入箱 | 150 / 168 / 196 / 415 | 海床 → 靠近 → 抓住 → 抬起搬运 | 闭合 f176 / 张开 f448 |

---

## 3. 标签本体

首版只保留能在单张 320×240 ego 帧里判定的 4 个谓词：

| 谓词 | 类型 | 语义 | 判定依据 |
|---|---|---|---|
| `OnSeabed` | 一元 | 物体静置海床 | 与海床接触、未被提起 |
| `InGripper` | 一元 | 被夹爪握持 | **夹爪已闭合 + 物体确实位于两指之间** |
| `Lifted` | 一元 | 提离海床 | 物体与海床之间出现可见间隙 |
| `NextTo(robot, obj)` | 二元 | 夹爪到达物体旁 | 指尖与物体距离 ≈ 一个物体直径以内 |

### 3.1 故意没标的三类

| 未标注项 | 原因（有据） |
|---|---|
| `Inside` / `InBox` | 抽查 1300、1302、1305、1313 等，物体被举到箱沿/箱口上方视频即结束。1302 末端张开指令在 f448，但 f465 物体仍在夹爪里，从未落入箱内。标成 `Inside` 属造假 |
| `Near` / `Reached` / `Aligned` | `target_pos`（6 维）整段多为 ~0 + 偶发跳变，与关节/末端运动不同步，坐标系与语义均未核实 |
| 场景中其他物体 | 部分 episode 还躺着另一个圆柱。未标 = 不参与差分，不会凭空生成「松开另一个物体」的动作 |

---

## 4. 题集构成

| 方向 | L=3 | L=4 | 合计 |
|---|---:|---:|---:|
| Forward | 28 | 7 | 35 |
| Inverse | 28 | 7 | 35 |

生成逻辑：每条 episode 4 个关键帧，构成有向无环图；L=3 有 4 条路径、L=4 有 1 条，双向合计 10 题/episode × 7 = 70 题。**没有用重复帧或等距帧凑数。**

题面示例（forward，`key_frame_ids=[140,213,328]`，`gt=[1,2]`）：

```text
[Action 1] The robot now becomes next to the blue cylinder.
[Action 2] The blue cylinder becomes grasped by the robot. The blue cylinder is now lifted
           above the seabed. The blue cylinder is not on the seabed anymore.
           The robot stopped being next to the blue cylinder.
```

---

## 5. 校验与基线成绩

### 5.1 自洽性校验

把参考答案当作预测喂回评测器，必须全对；否则说明场景图、动作签名、答案三者不一致。

| 输入 | 有效排列 | EM | TA | PA（逐题均值） | PA（转移加权） |
|---|---:|---:|---:|---:|---:|
| **参考答案** | 70/70 | **1.0000** | 1.0000 | 1.0000 | 1.0000 |
| 恒等 `[1,2,…]` | 70/70 | 0.4714 | 0.4714 | 0.5214 | 0.5130 |
| 逆序 | 70/70 | 0.3857 | 0.3857 | 0.5071 | 0.4805 |
| 随机（seed 0） | 70/70 | 0.3571 | 0.3571 | 0.4548 | 0.4416 |
| 空输出 | 0/70 | 0 | 0 | 0 | 0 |
| 畸形输出 `"[1, "` | 0/70 | 0 | 0 | 0 | 0 |

### 5.2 分设定的恒等捷径

| 设定 | 题数 | 恒等 EM | 随机 EM |
|---|---:|---:|---:|
| forward L=3 | 28 | 0.6071 | 0.4286 |
| forward L=4 | 7 | 0.2857 | 0.2857 |
| inverse L=3 | 28 | 0.4643 | 0.3571 |
| inverse L=4 | 7 | 0.1429 | 0.4286 |

**读法：L=3 只有 2 个动作，机会水平的 EM 就是 0.5。** 任何 L=3 分数都必须对着随机基线读，不能直接当「模型懂状态转移」。要让主指标更有分辨力，得增加 L=4/5 的路径——即每条 episode 再找出第 4 个语义变化。

---

## 6. 已修复的上游缺陷

| 缺陷 | 现象 | 处理 |
|---|---|---|
| 打乱种子被写死 | generator 内部 `random.seed(42)`，各 episode 打乱序列高度相关，**恒等答案占 60%**（机会仅 43%）——恒定输出 `[1,2]` 白拿 60 分 | `reseed_answers.py` 受控重排题面标签（前向重渲染图、逆向重排动作块），降到 47%；并逐题验证渲染图对应帧（槽位 1→f213、槽位 2→f328，像素差 0.0） |
| 字体路径写死 Linux | Windows 上标签退化为 10 px 位图字，「Next State 2」不可读，而前向题完全依赖该标签 | `usim_visual_prompt.py` 用系统 TTF 重绑渲染方法 |
| `image_root_path` 须为 `Path` | 传 `str` 时 `task_data.image_root_path.parent` 直接崩 | 适配层按 `Path` 传入 |
| 帧号偏移 | 上游 helper 首帧存 `00001.png`，USIM `frame_index` 从 0 起 | 严格按 `frame_index` 命名，首帧 `00000.png` |
| 解析容错改变分母 | 解析失败直接跳过，准确率被抬高 | 严格评测：固定分母，非法/缺失记 0 并单列原因 |

---

## 7. 已知问题与限制

1. **分辨率是标签可信度的瓶颈。** 320×240 下圆柱仅 10–15 px，「夹爪张开悬停」与「闭合握住」肉眼极难区分。本轮借夹爪关节信号定边界，但模型只看图——这批题对 VLM 偏难，部分题面证据不足。建议对夹爪—物体区域裁剪放大，或在 Stonefish 侧提高出图分辨率。
2. **`transfer` 示范不完整。** 需要重新采一段「末端释放并等待稳定 >1 s」的轨迹，才能覆盖「放入箱内」。
3. **`NextTo` 带主观性**（「一个物体直径以内」）。独立复核尚未执行。
4. **没有模型成绩。** 推理器已实现 OpenAI 兼容后端（vLLM / SGLang / Ollama 均可），接上即出分。
5. **上游 `--seed` 无效问题仍在**（generator 内部重置 42），所以走的后处理重排，而非改上游。

---

## 8. 复现命令（PowerShell，均已验证）

```powershell
Set-Location E:\code\UW-VLM\ENACT
$py = "C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
# 环境：Python 3.13.14 / numpy 2.4.6 / pyarrow 26.0.0 / opencv 4.13.0（Arrow 19 读不了这批 Parquet）

# 1) 帧与 Parquet 对齐核验
& $py scripts/usim/build_dataset.py --check --check-episodes 552,555,200,1302

# 2) 候选帧提案 + 联系人表（人工复核用）
& $py scripts/usim/propose_frames.py --episode 1302

# 3) 编译 ENACT 兼容目录（场景图 + 关键帧图）
& $py scripts/usim/build_dataset.py --overwrite

# 4) 生成双向 L=3/4 题集
& $py scripts/usim/build_qa.py --step-lengths 3,4

# 5) 受控重排题面标签
& $py scripts/usim/reseed_answers.py --seed 20261023

# 6) 自洽校验 + 基线
& $py scripts/usim/evaluate.py --synthetic oracle
& $py scripts/usim/evaluate.py --synthetic random --seed 0

# 7) 接入模型后出分（示例：本地 vLLM 服务 Qwen2.5-VL-7B-Instruct）
& $py scripts/usim/run_inference.py --backend openai --base-url http://127.0.0.1:8000/v1 `
    --model Qwen/Qwen2.5-VL-7B-Instruct `
    --out data/usim_enact/usim-enact-v0.1/predictions/qwen25vl7b.jsonl
& $py scripts/usim/evaluate.py --predictions data/usim_enact/usim-enact-v0.1/predictions/qwen25vl7b.jsonl
```

---

## 9. 产物与代码位置

```text
E:\code\UW-VLM\ENACT\
├─ enact\adapters\                         适配层（不改上游核心）
│   ├─ usim_reader.py                      LeRobot 读取、episode key、帧对齐校验
│   ├─ usim_scene_graph.py                 支持标注式布尔可见性的 SceneGraphReader
│   ├─ usim_visibility.py                  可见性记录与 provider
│   ├─ usim_annotations.py                 标注 schema、三值校验、场景图编译
│   ├─ usim_translator.py                  水下状态词表
│   └─ usim_visual_prompt.py               Windows 字体修复
├─ scripts\usim\                           流水线
│   ├─ build_dataset.py  build_qa.py  reseed_answers.py
│   └─ run_inference.py  evaluate.py  propose_frames.py  annotate_helper.py
├─ data\usim_enact\usim-enact-v0.1\        产物（约 32 MB）
│   ├─ manifest.json                       协议、USIM 清单哈希、ENACT commit、逐帧哈希
│   ├─ annotations\episodes\*.json         7 份人工复核标注
│   ├─ replayed_activities\<key>\          scene_graph_0.json + external_sensor1\NNNNN.png
│   ├─ segmented_activities\<key>\         关键帧场景图与图
│   ├─ QA\train\enact_ordering.jsonl       70 道题（build_summary.json 为构成统计）
│   ├─ QA\images\<qa_type>\<key>\*.png     带 Current / Next State 标签的题面图
│   ├─ predictions\                        推理输出（可断点续跑）
│   └─ evaluation\                         6 份基线 + 1 份自测报告，含逐题 items.jsonl
└─ docs\
    ├─ 07_reproduction_run.md              工程侧完整记录
    └─ WBW\ENACT-USIM复现结果-v0.1.md      本文档
```

---

## 10. 下一步（按性价比排序）

| 优先级 | 工作 | 目的 |
|---:|---|---|
| 1 | 接一个真实多图 VLM，先跑这 70 题 | 确认模型不是靠「恒等/固定顺序」过关 |
| 2 | 出「夹爪—物体裁剪放大」版题面，对比两种分辨率的 TA | 直接检验「证据不足」假设 |
| 3 | 再标注 5–10 条 episode 至 L=5（每条找出第 4 个语义变化） | 稀释 L=3 的 0.5 机会水平 |
| 4 | 争取 Stonefish 场景导出（物体位姿 / 接触 / 分割掩码） | 把 `InGripper`/`Inside` 从人工判断换成仿真真值，并解决 `target_pos` 语义 |

---

*协议版本 `usim-enact-v0.1`。本文所有数字均来自 `data\usim_enact\usim-enact-v0.1\evaluation\` 下对应 run 的 `report.json`，可按 §8 命令重跑复核。*
