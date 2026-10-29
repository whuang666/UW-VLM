# 保守候选：排列唯一性与oracle复算

后续进度：[均衡QA候选v1已独立构建](test_reserve_balanced_qa_build_20261029_zh.md)，20题新ID／64图已重新渲染和绑定，并重跑全部程序门禁。本报告保留旧诊断集的原始退化结果，不覆盖旧输入；当前独立验收仍0/10。

日期：2026-10-29（Asia/Shanghai）。输入版本：`test-reserve-conservative-20261029-v1`；本轮审计：`conservative-semantic-20261029-v1`。起点HEAD：`8197ef6`。

**程序门禁通过：10条完整候选链生成20道双向诊断题，穷举56个答案排列，每题恰好1个合法答案，oracle的EM／TA／PA均为1。** 空参考转移0、参考答案被拒0、多答案题0。

这证明给定候选状态、帧和原评分契约下的答案自洽性。独立人眼验收仍为 **0/10**，本轮没有产生真实模型成绩，也没有将这些诊断题发布为正式test。

后续[排列策略方案](test_reserve_permutation_strategy_20261029_zh.md)已实测常量策略20/20，并给出含恒等排列的均衡预览。“相邻转移互异”不能替代stock子集匹配下的接受集枚举，详见其合成反例；正式图片与QA尚未重建。

## 1. 范围与方法

输入：[保守候选清单](../../ENACT/docs/WBW/evidence/test_reserve_conservative_20261029/conservative_manifest.json)。8条pick保留3帧，2条transfer保留4帧；Lifted全部移出，transfer的OnSeabed也已移出。

候选annotation按字节复制到新的本地审计目录，不覆盖原件。复用stock `build_dataset.py` 编译，再为每条**全部保留帧**各生成1道forward及1道inverse诊断题，不生成子路径。诊断ID单独加前缀并标记`audit_only=true`，数据manifest绑定候选批次，`release_eligible=false`。

为什么这一步已有QA：现有评分器需要题目、参考排列及图片引用，才能枚举它实际接受的排列。因此先生成最小诊断夹具；正式test的题量、子路径、打乱方案、条件矩阵和输入冻结仍待另行构建。

随后复用原 `audit_qa_validity.py` 与 `evaluate.py --synthetic oracle`。审计脚本本身的exit0没有单独作为唯一性证明：新驱动额外要求每题`accepted_count=1`、参考答案属于接受集、参考签名非空，且题目／轨迹覆盖齐全。

来源与可复跑代码：

- [审计驱动](../../ENACT/scripts/usim/audit_conservative_candidates.py)。输出只能位于新的test复核子目录和新的证据子目录；拒绝写冻结数据或覆盖已有目录。
- [输入与源码哈希](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/analysis_plan.json)、[编译数据清单](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/compiled_dataset_manifest.json)。
- [20道诊断题](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/diagnostic_full_chain_qa.jsonl)、[全部排列及接受集](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/permutation_audit.json)。
- [机器汇总](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/summary.json)、[oracle报告](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/oracle.json)及[逐题结果](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/oracle.items.jsonl)。

## 2. 唯一性、分母与oracle

| 轨迹族 | episode数 | 方向 | 诊断题数 | 每题排列数 | 枚举次数 | 每题合法数 | 随机EM |
|---|---:|---|---:|---:|---:|---:|---:|
| pick L3 | 8 | forward | 8 | 2 | 16 | 1 | 1/2 |
| pick L3 | 8 | inverse | 8 | 2 | 16 | 1 | 1/2 |
| transfer L4 | 2 | forward | 2 | 6 | 12 | 1 | 1/6 |
| transfer L4 | 2 | inverse | 2 | 6 | 12 | 1 | 1/6 |
| 合计 | **10条独立轨迹** | 两方向 | **20** | — | **56** | **均为1** | **13/30≈0.4333** |

均匀随机EM按题平均：`(16×1/2 + 4×1/6) / 20 = 13/30`，不能用接受排列总数20除以枚举总数56替代。

oracle：20/20严格合法，invalid/missing=0，EM=TA=PA_item_mean=PA_transition_micro=1，计分参考转移共44个。10条annotation有32个关键帧和22个相邻转移；两个方向复用同一轨迹，不能把20题当作20条独立轨迹。

oracle直接使用给定参考答案，是编译／解析／评分链路自检；它没有证明候选标签对应的物理事实正确。

## 3. 重要限制：默认答案分布不能用于正式test

stock生成器每次使用固定seed42，本轮保留原实现，出现：

- 16道L3题的答案全部为`[2,1]`。
- 4道L4题的答案全部为`[1,2,3]`。

因此只按长度输出固定答案就能答对全部20道诊断题。这批题可验证评分链路，**不能直接当作正式test输入**。后续须在独立的新QA版本中确定打乱／重排策略并冻结，重新做全量唯一性、oracle、答案分布及图片清单检查，保留本轮诊断原件。

本轮没有完成正式题集的文本基线重算；也不把这些固定答案题上的任何程序得分解释成模型能力。

## 4. Transfer跨段转移

两条保留链为：start → approach → grasp → at_box。

| episode | 跨段端点 | 编译出的末转移 | at_box距open信号 | 程序结果 | 人眼状态 |
|---|---|---|---:|---|---|
| 1378 | f206→f448 | 仅新增`NearBox(robot,green_box)` | 15帧（open463） | 双方向各有唯一合法答案 | 独立验收待定 |
| 1384 | f239→f486 | 仅新增`NearBox(robot,green_box)` | 15帧（open501） | 双方向各有唯一合法答案 | 独立验收待定 |

两端都保持`InGripper=true`、`NextTo=false`；没有Lifted或OnSeabed从末帧重新进入scope。

本轮又查看4张原生ego端点图：红目标仍可见于夹爪附近，绿箱相对机器人／末端的位置与大小发生明显变化，端点图可供复核。该技术观察与“向箱子移动”一致；它没有代替NearBox“释放位置”的独立语义裁决，也没有验收被跳过的中间运动。open信号只用于窗口核对。

帧号、PNG哈希、末转移签名与技术观察见[跨段复核记录](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/transfer_pair_review.json)。`independent_ego_acceptance=pending`，没有回填任何worksheet为最终accepted。

8条pick保留的OnSeabed也只是本次程序审计的输入事实；唯一性和oracle不为其支撑可见性背书。独立复核若不能确认，须按既定规则从整条scope移除，并用新版本重新执行本轮门禁。

## 5. 源帧、测试及历史保留

- 核验20份ego视频／Parquet源文件哈希与固定USIM快照一致。
- 重新顺序解码10段ego视频，32个候选关键帧与编译出的raw／segmented两份PNG逐像素一致，确认未发生frame0或随机seek偏移。
- [94项现有测试](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/unit_test_receipt.json)全部通过，socket连接尝试0；[3项输出保护检查](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/boundary_checks.json)通过。
- [主冻结核验](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/freeze_verification.json)exit0，13组1818文件及payload哈希通过；原评分器与冻结输入未改。
- 源候选、初标、worksheet、旧评测与协议的[哈希保持回执](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/preservation.json)单独保存。

审计执行期间禁止socket连接，[连接尝试计数](../../ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1/network_receipt.json)为0。没有读取API凭据或执行真实模型推理；oracle是合成自检结果。

## 6. 复现与下一步

本地工作目录：

`ENACT/data/usim_enact/_review/test_reserve/conservative_semantic_20261029_v1/`

其中`source_annotations/`为10份原候选的字节副本，`dataset/`为独立编译产物，`diagnostic_full_chain_qa.jsonl`为诊断输入。PNG按既有规则留本地。源候选仍在原`_expansion/.../conservative_20261029_v1/`，本轮不覆盖它们。

仓库根目录复现，需本地源候选与固定USIM原始材料，输出使用新目录：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
& $py -X utf8 ENACT/scripts/usim/audit_conservative_candidates.py `
  --out ENACT/data/usim_enact/_review/test_reserve/conservative_semantic_reproduce_20261029 `
  --evidence-out ENACT/docs/WBW/evidence/conservative_semantic_reproduce_20261029
```

下一步构建正式QA候选时，先确定并版本化题量、长度范围及答案重排策略，生成图片／输入清单，再对**实际正式候选全量**重跑本轮门禁及文本基线。任何scope、帧或打乱变化均不直接继承这20题的审计结论。

独立人眼验收继续保留0/10，NearBox及保留的OnSeabed逐项确认；完成后才冻结最终test输入和运行协议。
