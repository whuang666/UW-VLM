# 签名复核后的处置、QA重建与输入快照

日期：2026-10-29（Asia/Shanghai）。实现版本：`signed-review-balanced-presentation-v1`。起点HEAD：`a6cdc81`。

**自动处理脚本已完成：[advance_signed_candidates.py](../../ENACT/scripts/usim/advance_signed_candidates.py)。它读取复核JSON并重新核对全部来源，输出接受／排除／待改／未决清单；在完整处置允许时，可继续重建新版本QA、图片、映射、基线和输入快照。**

它不固定生成18题，不替真人作裁决，也不把typed签名当作密码学身份认证。当前真实复核表仍空，实跑返回exit2、保留数0，未创建新测试集。真人验收仍 **0/10**，本轮API调用0。

## 1. 一条可直接使用的命令

真人从[验收页v2](../../ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2/review.html)导出自己的记录后，在仓库根目录运行：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
& $py -X utf8 ENACT/scripts/usim/advance_signed_candidates.py `
  --packet-dir ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2 `
  --reviews 'C:\path\to\completed_reviews.json' `
  --qa-version test-reviewed-qa-20261029-v1 `
  --out ENACT/docs/WBW/evidence/test_reviewed_release_20261029_v1 `
  --build-dataset ENACT/data/usim_enact/usim-enact-v0.2-reviewed-20261029-v1
```

`--out`与数据目录都必须不存在，避免覆盖已有证据。新数据目录必须使用独立的`usim-enact-v0.2-reviewed-*`名称；QA版本不能沿用父版本。只需要处置清单时省略`--build-dataset`，脚本不会写QA或图片。

exit2表示目前没有可继续重建的完整处置，如签名不齐、非独立声明、还有需改帧／scope的条目，或全部被排除。exit0表示处置已完成、且所请求的程序阶段成功，**并不等于最终test已发布**。运行失败的程序门禁会保留失败说明，不产生“构建成功”回执。

## 2. 它实际校验什么

每次都重新读取来源，不仅信任先前报告里的一个`passed=true`：

1. 复核bundle的schema、工作包版本和`packet_manifest_sha256`一致。
2. 工作包绑定的候选输入快照文件hash、payload hash、完整文件集合和每个文件hash都一致；源annotation和所有复核图／邻帧图的hash一致，路径保持在指定workspace内。
3. 复用现有校验器检查真实复核者／独立性／已见答案声明、逐帧scope、事实与原候选是否一致、visibility、转移、4项criteria、签名姓名、attestation及带时区签字日期。
4. 当前1650@f0的已知阻塞保留。对这一原快照签“接受”仍不通过，必须排除或完成另一个有证据的新版本裁决；脚本不预先替人写“排除1650”。

typed姓名、日期和声明能检查完整性、关联关系与自洽性，不能认证此人是谁。`identity_independently_authenticated=false`明确写入输出，项目负责人仍需核实实际复核者身份与独立性。这里只自动处理已有声明，不引入额外的在线签署服务。

## 3. 四类处置如何流转

| 输入处置 | 输出 | 是否自动构建新QA |
|---|---|---|
| `accept_current_snapshot`且完整合规 | `selected`，帧／scope原样保留，记录源annotation hash与签名bundle hash | 只有全部处置齐备且无待改项时才可继续 |
| `exclude`且完整合规 | `excluded`，保留原因和源绑定 | 不带入新QA |
| `changes_required`且完整合规 | `changes_required`，保留原因 | 阻塞本轮重建；先形成新帧／scope候选并复核 |
| 缺签名、空表、错误绑定、unknown或其余错误 | `unresolved` | 阻塞，不产出可采用的selection |

缺失／错误记录不会自动当作“排除”，以免把未完成验收伪装成已经裁决。所有条目排除时机会水平保留null，不伪造0%。

`selected`表示“按当前签名声明接受的输入”，不是模型评测放行清单。最终的`release_eligible`一直为false，直到另行完成最终协议／执行冻结流程。

## 4. 题量和机会水平按实际输入推导

当前父候选每条完整链每方向1题。脚本对每个接受episode核对这两道题的时间帧绑定，从实际长度计算`1/(L−1)!`，按实际题数加权，不使用固定18分母。

| 假设处置 | 新独立episode | 新QA | 随机EM期望 |
|---|---:|---:|---:|
| 只排除1650，其余9条均签接受 | 9 | 18 | **23/54≈0.4259** |
| 再排除另一条pick，其余8条均签接受 | 8 | 16 | **5/12≈0.4167** |
| 当前真实空表 | 0项可采用 | 不生成 | null |

7条L3／方向及2条L4／方向的18题情景中，均衡后的最佳长度常量为4/9，方向×长度最佳常量为5/9；不能沿用旧20题的0.45／0.50。脚本在实际重建后重新统计频数和位置矩阵，并实际评分固定identity／reverse及事后最佳常量。

两个方向来自同一episode；增加展示次数不增加独立轨迹数。最终不确定性分析仍应按episode分组。L4每方向只有2题时，EM步长依旧50pp。

## 5. 自动QA重建与重新验收

允许重建时，脚本只复制被签接受的**未改动**annotation、scene graph和原生帧，复制后再对照复核快照hash。源文件在载入后发生变化也不能静默进入新数据。无需重新随机seek或依赖尚未入库的`_expansion/`工作稿，这一步以已经复核的父候选快照为直接输入。

然后执行：

1. 对新组成按方向×长度在全排列空间均衡分配，包含恒等排列，保存新映射与seed。输入行顺序改变不影响分配。
2. 生成新QA ID；forward从原生图重排展示槽并重新标号，inverse保持时间图像并重排动作块。事实／visibility继续绑定时间帧，动作原文保留。
3. 全量检查原生帧→展示槽→标号图→答案，标号区外像素保留；输出源帧及图片hash清单。
4. 在**实际新QA**上枚举所有答案，要求每题恰好1个合法排列、参考可接受、参考签名非空；重新跑stock oracle、固定程序／常量及原文本基线。
5. 创建新输入快照，绑定签名bundle、packet、父输入快照、处置计划、验证报告、源码／字体、QA与图片hash及本轮门禁回执。

原标签／旧QA／历史模型预测均不覆盖。文本基线的inverse捷径不会因为新排列自动消失；其实际新结果必须单列报告。自动图文绑定也不能代替最终标号图是否遮挡对象等视觉抽检。

## 6. 主要输出文件

| 文件 | 内容 |
|---|---|
| `review_bundle.json`／`packet_manifest.json` | 原始签名记录与原packet的字节副本 |
| `review_validation.json` | 本次重新核验的身份声明、签名与逐条门禁结果 |
| `review_dispositions.json` | selected／excluded／changes_required／unresolved四类清单与原因 |
| `selection_plan.json` | 接受项帧／scope／源hash、实际题量、精确随机分数与是否可重建 |
| `flow_input_manifest.json` | packet／签名／父快照及本次实现依赖源码hash |
| `mapping.json`／`image_bindings.json` | 新题的编号映射与全部图像来源绑定 |
| `answer_distribution.json`／`program_baselines.json` | 新题量下的排列频数、常量下限及实际程序得分 |
| `permutation_audit.json`／`oracle.json`／`text_baseline.json` | 实际新题集的程序门禁 |
| `rebuild_gates.json` | 本次程序结果及仍未完成的身份／执行冻结状态 |
| 数据目录下`candidate_input_snapshot.json` | 新版本所有输入的hash快照；最终执行协议尚未冻结 |
| `summary.json` | 阻塞／成功、实际组成和是否写了新QA；失败不伪报成功 |

若仅完成清单阶段，后半段QA／图片文件不存在，这在`summary.json`中明确标记。程序完整执行也保持`release_eligible=false`，不调用API。

## 7. 已实跑的验证

真实路径：[当前空表入口回执](../../ENACT/docs/WBW/evidence/signed_review_flow_20261029_v1/actual_unsigned_final_verifiedcopy/summary.json)为exit2，阻塞原因`incomplete_or_unqualified_review_declarations`，接受数0，真实`usim-enact-v0.2-reviewed-20261029-v1`目录未创建。

正向路径用**完全虚构的fixture**，不是给真实样本伪造签字。fixture中9条接受、1条排除，完成18题／58展示图的重建，52个排列枚举均唯一，oracle18/18；146份合成输入资产hash全部匹配，机会水平23/54、常量4/9与5/9。该演练的文本分数只属于虚构题面，不能移植为真实18题结果。

详见[合成演练回执](../../ENACT/docs/WBW/evidence/signed_review_flow_20261029_v1/smoke_receipt_verifiedcopy.json)、[演练脚本](../../ENACT/docs/WBW/evidence/signed_review_flow_20261029_v1/exercise_flow.py)和[新增回归测试](../../tools/test_signed_candidate_flow.py)。合成图片、表和签名fixture在忽略的`_review/.../tools_out/`目录，不计入真实验收、不进入正式测试。

新增14项测试覆盖实际题量变化、未签名／非真人声明、全部排除、待改帧／scope、null结构、错packet／原生图hash、行顺序、复制后二次核对、重建失败记录和完整实际评分。全量132项测试通过，socket连接尝试0；旧1818文件冻结通过，551份旧文件hash未变。详见[最终测试](../../ENACT/docs/WBW/evidence/signed_review_flow_20261029_v1/unit_test_receipt_release.json)、[旧冻结](../../ENACT/docs/WBW/evidence/signed_review_flow_20261029_v1/old_freeze_verification.json)及[文件保持](../../ENACT/docs/WBW/evidence/signed_review_flow_20261029_v1/preservation.json)。

## 8. 自动流程的终点

这次实现止于“复核声明绑定的新QA候选＋程序门禁＋输入快照”。真实身份核实、最终标号图抽检、A/B/C/D派生条件、模型请求协议／预算、按episode统计方案和最终执行冻结仍需完成。不能把合成成功、exit0或oracle1.0当成真实test准入。

当前真实独立验收仍0/10；本轮未提交／推送，没有把假设18题写成已经验收的最终题集。用户报告`a6cdc81`已推送，本轮只读远端查询遇连接重置，未再次独立确认远端SHA。
