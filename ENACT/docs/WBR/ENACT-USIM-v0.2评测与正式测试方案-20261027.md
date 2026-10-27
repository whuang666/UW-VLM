# ENACT × USIM v0.2 评测与正式测试方案

版本：2026-10-27（Asia/Shanghai）。项目：`E:\code\UW-VLM\ENACT`。
本文是 v0.2 的**评测契约草案**；数据与题集数字在构建完成后由 `usim-enact-v0.2/manifest.json`、`QA/train/*.manifest.json` 与协议冻结文件固定，本文只规定方法与门禁。v0.1 结果（qwen3.8-max 开发集 EM 0.9571 / 去图 0.7286）继续作为历史开发结果，不与 v0.2 混报。

## 1. 背景：v0.1 暴露的四个方法问题

1. **L=3 无分辨力**：v0.1 的 56/70 是 L=3，机会 EM=0.5；forward L=3 的随机 PA 期望 0.625。
2. **inverse 基本是文本题**：程序化文本先验基线（只读题面动作文本、不看图）inverse EM=35/35、总体 0.7714，高于模型去图条件 C 的 0.7286 → v0.1 的 inverse 分数不能读成视觉世界建模能力。
3. **标签模板化且未独立复核**：7 条 episode 的 4×4 事实表完全相同；独立复核（`_review/round2/`）把 "21 转移均可见" 修正为模板推论，并发现 3 处 `OnSeabed` 物理证据缺失 + 2 处可见性错误。
4. **对照条件存在版本混杂**：v0.1 的 A/B/C 三次 run 使用了 3 个不同版本的 `run_inference.py`（P1），正式对照必须同版本重跑。

v0.2 的对策：扩轨迹（20 条 dev/val + 10 条 test 预留）、每条约 5–6 个可辨状态帧以支持 L=4/5、标签语义修正并在规范中显式化、评分 gate 升级 v0.3、条件矩阵补齐 text-only / no-text / 程序基线、正式 test 冻结后才构建。

## 2. 数据版本 `usim-enact-v0.2`

| 组成 | 数量 | 说明 |
|---|---:|---|
| v0.1 迁移 | 7 条 | 修正 `OnSeabed` 物理支撑语义（7 处）、可见性 2 处（555/f140、556/f180）、notes（red fish）；`NextTo` approach 语义；仍为 4 帧/L≤4 |
| 新增 dev | 12 条 | 逐帧独立标注，5/6 帧，尽量支持 L=5 |
| 新增 val | 8 条 | 同上；只用于选择与错误分析 |
| **合计（开发/验证）** | **27 条** | dev 19 / val 8（v0.1 的 7 条全部归 dev） |
| test 预留 | 10 条 | `_expansion/annotation_assignment.json` 的 test_reserve；**协议冻结后才标注**；外层的 USIM `test/` 525 条全程不用 |

- 长度结构（构建结果）：27 条中 3 条 transfer（1304/1318/1357，各 5 帧）支持 **L=5**（at_box / `NearBox(robot,green_box)` 路线）；1330 缺 start 帧支持 L≤4；其余 pick 轨迹 4 帧（980 仅 3 帧）→ L≤4。即 20 条新增中 **3/20 = 15% 支持 L=5**。
- 已知限制：transfer 块 100/100 条无可用 `InBox` 证据（释放距末帧 16–18 帧、目标质心始终在箱外、无沉降）；pick 轨迹无 release_settle；`touching` 在 ego 渲染保持结构下无稳定独立帧。因此 L=5 只来自 at_box，且 at_box 是定性 ego 判断（partial，无距离阈值）。

- 划分按 episode；同一 episode 的方向、长度、图片版本同属一个 split。
- 迁移清单：`usim-enact-v0.2/migration_v01_to_v02.json`（逐条 changed_facts / changed_visibility / 迁移后转移文本）。
- 标注规范：`docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md`（含复核裁决 §8）。
- 已知限制（必须进报告）：新增标注为 1 名标注者 + Lead 抽检，不是双人独立标注；`ego-only` 对距离/接触/离底存在 partial；v0.1 迁移条目保留其原始 4 帧选择。

## 3. 题集构建（构建门禁）

流程（全部命令保存为可复跑证据）：

1. `build_dataset.py --annotations usim-enact-v0.2/annotations/episodes --out usim-enact-v0.2`
   - 要求：全部标注通过 schema；相邻转移可见数在 manifest 中记录。
2. `build_qa.py --data-root usim-enact-v0.2 --step-lengths 3,4,5 --num-to-sample 25`
3. `reseed_answers.py --data-root … --seed 20261027`
   - 固定 seed 重排标签；记录 identity 率（随机期望 `1/(L−1)!`：L=3 为 0.5、L=4 为 1/6、L=5 为 1/24）。
4. `curate_qa_v02.py --quotas 5:2,4:3,3:1 --seed 20261027`
   - 按路径配对 forward/inverse；L=5 全收、L=4 次之、L=3 只保留每 episode 每题方向 1 条（v0.2 的 L=3 仅用于与 ENACT/v0.1 兼容对照，机会水平 0.5）；
   - **选择规则在看模型成绩前固定**，不允许按模型表现反复调 seed/配额。
5. `audit_qa_validity.py`（gate）
   - 要求：参考排列全部被 verifier 接受；0 个空/不可见参考转移；报告多选题数与精确随机期望。
6. `make_splits_v02.py` → dev/val（test 在冻结后另建）。

**验收**：`evaluate.py --synthetic oracle` 全 1.0；身份排列率与理论期望相容；每 setting 的 N、图片数、哈希写入 manifest；任何门禁失败即停止，不得用删题/改答案绕过。

## 4. 评分协议 `usim_strict_v0.3`

在 v0.2 的基础上（固定分母、严格解析、缺资产即失败、重复/未知 ID 拒绝）增加：

- **参考转移可见性 gate**：precheck 对每题每个参考转移计算可见签名；若存在空/不可见参考转移 → `AssetError`、退出非零、不发布报告。v0.1 的 0 空签名不受影响；v0.2 若出现漏标将直接失败而不是虚假满分。
- **多合法顺序契约**：`check_scoring_contract_v2.py` 用合成样例覆盖 (a) ≥2 语义合法顺序都 TA=1 且 EM 只认参考；(b) 不可交换动作交换后 TA=0；(c) 空签名拒绝；(d) 固定分母边界；(e) 重复/未知 ID。真实题集若多答案=0，报告必须写 "TA≡EM（该题集未出现语义等价多解）"。
- **报告字段**：`dataset_version`、`evaluation_protocol`、`qa_sha256`、每 setting 的 N / 合法排列数 / 失败与格式错误数 / EM / TA / PA_item_mean / PA_transition_micro / identity_reference_rate / 精确随机期望。

## 5. 条件矩阵与程序基线

同一批冻结 QA ID、同一模型与解码参数；每条件独立 run 目录：

| 条件 | 输入 | 回答的问题 |
|---|---|---|
| A 原图 | ego 帧全图（现有 QA 图） | 正式主条件 |
| B 局部放大 | 每状态 `[原图 320×240 \| 局部 320×240]` | 小目标可读性（天花板效应下可能无可测增益） |
| C 去图 | 不传图片，仅题干 | 文本先验能解释多少 |
| D 去动作文本 | forward 题干删除 `Actions in Order`，改为"按时间顺序排列未来状态图" | 纯视觉时序排序能力（clean visual signal） |
| 程序基线 | oracle / identity / reverse / uniform-random / **text-prior** | 机会水平、固定顺序捷径、文本可解程度 |

- **文本先验基线**（`scripts/usim/text_prior_baseline.py`）必须与 A/B/C/D 同表报告；inverse 若被文本基线全解，inverse 结果只作"文本+视觉对齐"解读，不作视觉能力证据。
- 每个条件报告：
  - direction×L 分层；任务与 episode 分层；
  - 按 episode 分组的 bootstrap CI（重采样 episode，不重采样题）；
  - A−C、A−D、A−B 的同 ID 配对差值与区间；
  - 失败/格式错误/缺失计数与原因；
  - identity 答案率 vs 参考率。
- **文本可解分层**：用 text-prior 基线把题分成"文本可解"与"文本不可解"两层分别报模型准确率（forward L≥4 是主要视觉信号）。

## 6. 模型与提示词冻结

沿用 v0.1 冻结配置（见 `docs/WBW/ENACT-USIM-qwen3.8-max-执行结果-20261024.md` §1）：

| 项 | 冻结值 |
|---|---|
| 模型 | `qwen3.8-max`（别名模型；保存 request_id、响应 model 与调用时间；不承诺底层快照） |
| 提示策略 | 方案 A：无 system message；user 末尾格式指令 |
| 格式指令 | `Respond with ONLY the Python list of integers…`（sha256 记入冻结） |
| 解码 | `temperature=0`、`enable_thinking=false`、`max_completion_tokens=256`、`stream=false` |
| 传输 | `timeout=180s`、`max_attempts=3`、串行 + sleep 1s |
| 图像 | 原图 320×240；B 条件合成图规则冻结（`build_crops.py`）；C 用 `--drop-images`；D 用 `build_condition_d.py` |

**P1 修复要求**：A/B/C/D 四条件必须在**同一个 `run_inference.py` 源码版本**上运行（v0.1 的 A/B/C 来自 3 个不同版本）；冻结文件记录每次 run 的源码哈希。

## 7. 正式 test 协议（冻结后）

1. **冻结**（test 构造前）：标签规范版本、可见性规则、选帧规则、prompt 与格式指令、模型与解码参数、评分版本（`usim_strict_v0.3`）、题集筛选配额与 seed、源码哈希；产出 `data/usim_enact/_protocol/freeze_v0.2_*.json` 并 `--verify` 通过。
2. **构造 test**：用冻结规则标注 test_reserve 的 10 条 episode（标注者不参考任何模型在 test 上的输出），按同一构建/筛选/重排流程生成 test QA；test QA 哈希写入冻结清单；`audit_qa_validity` + oracle + v0.3 gate 必须通过。
3. **运行 test**：A/B/C/D 与程序基线各跑一遍；只报告一次，不得据 test 结果调整 prompt/参数/配额。
4. **报告**：按 §5 口径；公开 test 的 ID、哈希、run 目录与失败记录；标签若在 test 后发现错误 → 升版本（v0.2.1）并对全部条件重评，不允许只删模型答错题。
5. **API 密钥**：正式 test 需要 `VLM_API_KEY`（环境变量，不落盘）；当前会话无密钥，因此本阶段只完成到"test 候选登记 + 冻结方案 + dry-run 输入校验"。

## 8. 复现命令（v0.2 开发集，模板）

```powershell
Set-Location 'E:\code\UW-VLM\ENACT'
$py  = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$v2  = 'data\usim_enact\usim-enact-v0.2'
$run = 'data\usim_enact\runs\qwen3.8-max\v02_dev_001'

# 0) 标注迁移（v0.1 七条，只读原文件）
& $py scripts\usim\migrate_v01_to_v02.py --annotations data\usim_enact\usim-enact-v0.1\annotations\episodes --out "$v2\annotations\episodes"

# 1) 数据 + 题集 + 重排 + 筛选
& $py scripts\usim\build_dataset.py --annotations "$v2\annotations\episodes" --out $v2
& $py scripts\usim\build_qa.py --data-root $v2 --step-lengths 3,4,5 --num-to-sample 25
& $py scripts\usim\reseed_answers.py --data-root $v2 --qa "$v2\QA\train\enact_ordering.jsonl" --seed 20261027
& $py scripts\usim\curate_qa_v02.py --data-root $v2 --qa "$v2\QA\train\enact_ordering.jsonl" --out "$v2\QA\train\enact_ordering_curated.jsonl"

# 2) 门禁
& $py scripts\usim\audit_qa_validity.py --data-root $v2 --qa "$v2\QA\train\enact_ordering_curated.jsonl" --out data\usim_enact\_protocol\audit_qa_validity_v0.2.json
& $py scripts\usim\evaluate.py --data-root $v2 --qa "$v2\QA\train\enact_ordering_curated.jsonl" --synthetic oracle --out "$run\baseline_oracle.json"
& $py scripts\usim\make_splits_v02.py --qa "$v2\QA\train\enact_ordering_curated.jsonl" --out-dir "$run\inputs"
& $py scripts\usim\build_condition_d.py --data-root $v2 --qa "$v2\QA\train\enact_ordering_curated.jsonl" --out "$v2\QA\train\enact_ordering_curated_no_text.jsonl"

# 3) 真实模型（需要 VLM_API_KEY；四条件同一源码版本）
#    A/B/C/D 用 run_inference.py 分别输出到 $run\A / B / C / D，再用 evaluate.py + report_stats.py
& $py scripts\usim\check_scoring_contract_v2.py
& $py scripts\usim\freeze_protocol.py --self-test
```

## 9. 风险与限制（写进结果报告）

1. 文本先验：inverse 仍可被程序化文本基线解出（v0.1 为 35/35）；v0.2 只能通过 forward L=4/5 + 条件 D + 文本可解分层来分离视觉增益。
2. 单标注者：v0.2 新增标注没有双人独立复核；Lead 抽检不能替代正式标注者间一致性（可后续补 2 条双标计算一致率）。
3. ego-only 可判性：距离/接触/离底在 320×240 下有 partial；报告必须分列 "标签值" 与 "ego 可判性"，条件 B 的负结果不能解释为"分辨率无关"。
4. 渲染保持：USIM ego 视频是低帧率渲染（每 episode 35–57 个唯一画面），"±10 帧稳定"不等于信息量。
5. 别名模型：`qwen3.8-max` 底层快照可能变化；只能记录调用时间、request_id 与响应 model。
6. test 规模：10 条 episode 的题量有限，CI 宽度会较大；按 episode 分组报告，不把同 episode 的多题当独立样本。
