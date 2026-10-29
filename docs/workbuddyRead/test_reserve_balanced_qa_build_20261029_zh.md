# 保守候选均衡QA v1：构建、图文绑定与门禁

日期：2026-10-29（Asia/Shanghai）。起点HEAD：`4d5ec41`。

**新QA候选已构建：10条轨迹、20题、64张标号图，按已确认的20行映射生成，独立于旧诊断集。56次实际答案排列枚举均为唯一解，oracle20/20，均衡门禁通过。**

版本为`test-reserve-balanced-qa-20261029-v1`，数据目录为：

`ENACT/data/usim_enact/usim-enact-v0.2-conservative-balanced-20261029-v1/`

这是可复核的候选输入版本，`release_eligible=false`、独立验收仍 **0/10**。新标号图的视觉检查又发现源帧`1650@f0`无法辨认目标管子，需要裁决；因此没有将20题直接放行为正式test。模型API调用0。

## 1. 版本与入口

| 角色 | 版本／产物 |
|---|---|
| 标注输入 | `test-reserve-conservative-20261029-v1`，10份annotation按字节复制，原件保留 |
| 排列策略 | `test-reserve-balanced-labels-draft-v1`，seed20261029，逐行采用既定预览 |
| 新QA | `test-reserve-balanced-qa-20261029-v1`，20个新ID，与旧诊断ID无交集 |
| 题集 | [新QA JSONL](../../ENACT/data/usim_enact/usim-enact-v0.2-conservative-balanced-20261029-v1/QA/candidate/enact_ordering_balanced.jsonl) |
| 数据来源 | [新数据manifest](../../ENACT/data/usim_enact/usim-enact-v0.2-conservative-balanced-20261029-v1/manifest.json) |
| 输入锁定 | [候选输入快照](../../ENACT/data/usim_enact/usim-enact-v0.2-conservative-balanced-20261029-v1/candidate_input_snapshot.json)，锁定160份输入文件；这是构建快照，不是最终执行协议冻结 |
| 构建器 | [build_conservative_balanced_qa.py](../../ENACT/scripts/usim/build_conservative_balanced_qa.py) |
| 复核器 | [verify_built_qa.py](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/verify_built_qa.py) |
| 机器证据 | [summary.json](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/summary.json)、[发布门禁](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/release_gate.json) |

原生候选仍是8条pick L3及2条transfer L4；没有因打乱而改变事实、scope、物理事件顺序或帧号。源annotation的v0.2适配字段与`conservative_version`原样保留，候选批次／QA版本由新manifest及快照显式绑定，避免仅靠目录名区分。

## 2. 具体重建了什么

forward的Current State保持原始起点，其余未来帧按展示槽重新排入，从未标号的原生PNG重新绘制`Next State N`。动作原文与时间顺序保持，`gt_answer`改为预览指定映射。

inverse的图像继续按时间顺序，图片编号仍对应时间项；将旧动作块还原到时间顺序，再按新映射重排动作／编号，保留每句原文和动作块之外的题干。不存在把p本身误当展示列表的问题：`p=[2,3,1]`对应展示时间项3／1／2。

构建器使用真实字体及明确渲染参数，缺字体、缺源图或标签越界直接报错。全量[图像绑定清单](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/image_bindings.json)逐一记录64个展示槽的源帧、原生哈希、输出哈希、标号区域、annotation哈希与源visibility。

程序核验同时要求：图像与指定源帧及编号完全一致，标号区域外的原生像素不变，visibility仍绑定原时间帧。另用原有`usim_visual_prompt.render_label`重新渲染64图，结果全部逐像素一致。新驱动的正反映射／渲染实现没有作为唯一校验来源。

20份ego视频／Parquet源文件均匹配固定快照；再次顺序解码10条视频，32个关键帧与新raw／segmented两份PNG逐像素一致，视频帧数与Parquet行数相等。

## 3. 答案分布与常量门禁

| 层 | 题数 | 实际答案频数 | 最佳该层常量EM | 单题EM步长 |
|---|---:|---|---:|---:|
| forward L3 | 8 | `[1,2]`4、`[2,1]`4 | 4/8 | 12.5pp |
| inverse L3 | 8 | `[1,2]`4、`[2,1]`4 | 4/8 | 12.5pp |
| forward L4 | 2 | `[1,2,3]`1、`[3,1,2]`1 | 1/2 | 50pp |
| inverse L4 | 2 | `[2,1,3]`1、`[2,3,1]`1 | 1/2 | 50pp |

层内计入所有未出现的排列后，频数最大差≤1、多样性达到`min(N,M)`；最佳常量达到当前N下的最小可能值`ceil(N/M)/N`。L4没有被错误要求达到不可实现的1/6经验最佳常量。

按长度选常量时，L3合计16题的最多命中数8，L4合计4题的最多命中数1，实测 **9/20=0.45**。按方向×长度选常量时实测 **10/20=0.50**。随机均匀排列的EM期望仍为 **13/30≈0.4333**。常量上限不是都等于随机。

[频数报告](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/answer_distribution.json)还给出每层“时间项×展示槽”位置矩阵；均衡排列频数不保证小样本的各位置边际都均匀。

L4每方向仅2题，只能报告0/2、1/2、2/2，不将小数显示位数解释成分辨力。扩至6条独立轨迹／方向并均匀覆盖6排列是一个最小均衡块；“N≥6”本身并不自动保证最佳常量≤1/6，例如N=7时理论下限是2/7。

## 4. 实际QA上的唯一性、oracle与文本基线

对新生成的20题使用stock verifier枚举56次答案排列：每题恰好1个合法排列，参考答案拒绝／空参考签名／多答案题均0。oracle20/20严格合法，EM／TA／PA_item／PA_micro均1；没有以“转移互异”替代枚举。

新输入上重新计算的结果：

| 本地程序 | 完全匹配EM | 解释 |
|---|---:|---|
| 合成oracle | 20/20=1 | 编译、参考映射与评分自检 |
| 固定identity | 9/20=0.45 | 不按测试成绩调节的固定排列 |
| 固定reverse | 8/20=0.40 | 同上 |
| 按长度最佳常量 | 9/20=0.45 | 事后标签频数审计，不是模型能力 |
| 按方向×长度最佳常量 | 10/20=0.50 | 同上，达到当前样本量下限 |
| 既有文本程序基线 | **15/20=0.75** | forward5/10、inverse10/10 |

文本基线使用原`text_lifecycle_v2`规则，未针对新题改规则；它从动作措辞恢复inverse顺序，forward使用identity。inverse10/10说明展示均衡没有消除题面动作文本捷径，不能把未来inverse模型高分解读成视觉能力。0.75是程序基线成绩，尚无真实VLM结果。

证据：[排列审计](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/permutation_audit.json)、[oracle](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/oracle.json)、[文本基线及分层](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/text_baseline.json)。所有分母保留完整题集；20题仍只来自10条轨迹。

## 5. 新视觉复查：1650@f0必须裁决

已查看5页contact sheet，覆盖20题／64张标号图，并额外打开1650及1078的原生f0对照。文字清晰，未观察到新编号遮住目标；标号区域外像素一致性也通过。

**1650的原生f0中未能辨认出管子，源annotation却标目标visibility=true。** 相同源帧用于该episode两个方向的Current State，共影响2题。新构建忠实保留了原帧，无法辨认的区域不在新标号遮挡范围内，因此不能把这项争议归因于重新编号。

本轮没有擅自将visibility改成false或重选帧；该事实需要逐帧证据与独立裁决。候选保留20题，发布门禁明确阻塞，并记录[技术视觉检查](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/visual_review.json)。若后续换起点或删除episode，题集必须再建版本，重新分配均衡映射并跑全量门禁；不能直接继承目前20题的通过回执。

其他保留的OnSeabed、NearBox及跨段转移仍待独立语义验收。这里完成的是输入重建、展示一致性与程序门禁，不是10条标签已被最终认可。

## 6. 验证、保存及复现

- 全量 **105项测试**（原94项＋新增11项）通过，0失败／错误／跳过，测试进程socket连接尝试0。新增测试覆盖非自逆3循环、已打乱输入再编号、动作原文保留、退化分布、有限样本下限、冻结目录保护、错源像素及false visibility拒绝等。
- 原评分契约检查exit0，输出回执重定向到本轮证据目录；原评分器源码与既有契约证据不改。
- 原13组1818文件冻结核验exit0、payload匹配；新候选快照的160份输入文件／完整文件集合／payload核验通过，64图经stock渲染器重放一致。
- 本轮构建、基线及测试的socket尝试均0，无API调用；没有创建真实模型predictions或运行val／test推理。

见[测试回执](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/unit_test_receipt.json)、[独立程序复核](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/independent_verification.json)、[旧冻结核验](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/old_freeze_verification.json)及[文件保持记录](../../ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/preservation.json)。程序复核不等同独立人眼标注。

证据目录：`ENACT/docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1/`。原生与正式候选标号图在新数据目录中，临时contact sheet在`_review/test_reserve/balanced_qa_visual_20261029_v1/`并按既有规则忽略。新QA与图片是独立候选资产，尚未提交或发布；不force-add临时复核PNG。

仓库根目录复现到全新目录：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
& $py -X utf8 ENACT/scripts/usim/build_conservative_balanced_qa.py `
  --out ENACT/data/usim_enact/usim-enact-v0.2-conservative-balanced-reproduce-20261029-v1 `
  --evidence-out ENACT/docs/WBW/evidence/balanced_qa_reproduce_20261029_v1
```

输入包括本地保守候选与已固定USIM源文件。驱动拒绝覆盖旧输出；已有候选可运行证据目录中的`verify_built_qa.py`只读核验原快照与图文绑定。

下一步先裁决1650@f0并完成独立质量验收；A/B/C/D条件派生和最终请求／统计协议按新QA指纹另行准备。当前候选不继承旧294／588次开发模型成绩。
