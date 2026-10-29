# 验收页真实交互测试与v2修复

日期：2026-10-29（Asia/Shanghai）。起点本地HEAD：`150ca74`。

**已在真实Edge浏览器中完成“试填一份 → 下载JSON → 重新导入 → 再次下载 → 下游校验”的闭环，并修复了损坏JSON导入会覆盖已有填写内容的缺陷。请使用[验收页v2](../../ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2/review.html)。**

所有试填均用`AUTOMATED_UI_TEST_NOT_A_HUMAN_REVIEW`身份，`reviewer_is_human=false`、`reviewer_independent_of_first_pass=false`。测试选择和签名控件只用于检验界面数据传递，文件单独放在忽略的`tools_out/`目录，不属于人眼验收记录。真实的10份空表保持空白，独立验收仍0/10，模型API调用0。

## 1. 从浏览器实际确认的结果

使用Playwright驱动headless Microsoft Edge打开本地页面；不是静态HTML计数，也不是直接修改页面内部的bundle对象。

| 测试 | v1结果 | v2结果 |
|---|---|---|
| 浏览器渲染10个episode区块，94图均实际解码 | 通过 | 通过 |
| 空页面直接导出与原空白模板JSON值完全一致 | 通过 | 通过 |
| 逐控件填写第1份表：事实、可见性、依据、转移、4项criteria、处置、测试签名 | 通过 | 通过 |
| 点击下载获得JSON，全部模板字段保留，另外9份表仍空 | 通过 | 通过 |
| 刷新后从文件选择器导入，再导出JSON值完全一致 | 通过 | 通过 |
| 不同packet hash导入失败，已有内容保留 | 通过 | 通过 |
| 同packet hash但`worksheets[0].frames=null` | **失败：旧状态被替换，渲染区块消失** | **拒绝且原状态与10区块全部保留** |
| 错源帧号／字符串布尔值／缺attestation字段 | v1未设完整嵌套形状检查 | 拒绝且原状态保留 |
| 多次失败后重新选择同一有效文件 | — | 正常导入并保持值一致 |
| 导出内容交给Python下游 | 正常文件可解析 | 正常与损坏文件均能形成明确拒绝报告；没有错误准入 |

“下游通过读取格式”与“人眼验收通过”是两件事：自动化身份和其余空表使完成数／接受数均为0，exit2符合预期。第1份synthetic worksheet的结构、证据文本和签名字段没有缺失，但人类身份声明明确为false，因此不会计入独立验收。

浏览器HTTP／HTTPS请求全部拦截，运行期间请求计数0，页面无未捕获JavaScript错误。截图已查看确认真实控件填写与显示，临时截图保持本地。

证据：[v1缺陷复现](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/v1_reproduced_result.json)、[v2完整结果](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/v2_interaction_result.json)、[自动化导出下游回执](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/synthetic_validator_v2_interaction_result.json)、[损坏结构下游回执](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/malformed_downstream_v2_interaction_result.json)。

## 2. 缺陷根因与修复

旧导入代码只检查packet hash、worksheet数量和episode顺序，就先执行`bundle=value`，随后调用render。若嵌套frames变成null，render抛错，但旧bundle已被覆盖；catch只显示错误，不能恢复用户进度。损坏JSON甚至可能在下一次点击导出时被原样下载。

v2在替换状态前完整校验字段结构、数组长度、类型、判定值、源帧号、annotation／PNG哈希、谓词和arguments绑定。只有全部检查通过才复制到当前状态；如果渲染出现异常，回滚到先前bundle。失败时明确显示“原填写内容已保留”，并重置文件选择控件，允许再次选择相同文件。

Python下游新增嵌套结构检查：null列表、非对象worksheet、字符串布尔值、整数充当bool、缺失文本等形成明确拒绝结果，避免先在`.strip()`或循环处崩溃。原本的身份独立性、签名、事实分歧和1650@f0阻塞门禁继续保留。

改动源码：[HTML模板](../../ENACT/scripts/usim/templates/acceptance_workpack.html)、[工作包构建器](../../ENACT/scripts/usim/prepare_acceptance_workpack.py)、[下游校验器](../../ENACT/scripts/usim/validate_acceptance_reviews.py)、[回归测试](../../tools/test_acceptance_reviews.py)。

最初一次测试脚本的成功汇总也存在bool继承int导致False被算为成功的问题；已修正汇总，并用新输出目录再次复现v1失败。应以`v1_reproduced_result.json`的`passed=false`和v2的`passed=true`为准，未将初次错误汇总当作通过证据。

## 3. 版本与现有记录

| 项 | 状态 |
|---|---|
| 原工作包v1 | 页面、清单、空模板及争议表保留原字节 |
| 新工作包 | `test-human-acceptance-workpack-20261029-v2`，与当前同一20题候选快照绑定 |
| v2空表 | 10份；不包含自动化测试的输入值 |
| 当前候选数据集／旧QA／历史模型预测 | 不修改 |
| 真实独立验收 | 0/10 |
| 1650@f0 | 阻塞保留；后续处置仍需新版本重建 |

v1与v2的packet版本／hash不同，旧导出不会被v2静默接受。这是避免错包混用；如有人已用v1形成真实记录，保留原文件，用对应v1包校验后再作显式迁移，不手工篡改hash。

本轮开始时确认，`150ca74`提交包含页面及文档证据，但工作包构建器、模板、Python校验器与测试文件仍未被Git跟踪。因此后续提交需显式包括上述4份源码／测试以及本轮验证脚本；只提交HTML会遗漏下游和重建实现。逐文件hash见[源码交付清单](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/source_delivery.json)。本轮没有执行git add、commit或push。

## 4. 使用与复现

从[验收页v2](../../ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2/review.html)填写并导出自己的JSON。当前校验器默认packet目录也已切换v2；可显式指定避免混用：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
& $py -X utf8 ENACT/scripts/usim/validate_acceptance_reviews.py `
  --packet-dir ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2 `
  --reviews 'C:\path\to\completed_reviews.json' `
  --out ENACT/docs/WBW/evidence/test_human_acceptance_20261029_v2/review_validation_completed.json
```

浏览器闭环复现使用新work目录和新result文件名：

```powershell
& $py -X utf8 ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/run_interaction_check.py `
  --packet-dir ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2 `
  --work-dir ENACT/data/usim_enact/_review/test_reserve/acceptance_ui_replay_20261029/tools_out `
  --result-name v2_replay_result.json
```

浏览器烟测需要本地Python Playwright及Microsoft Edge，不产生模型请求。它会填写合成记录并保存在独立忽略目录，下游必须拒绝其作为人眼验收；不能将这些测试导出拿来更新项目accepted数量。

## 5. 验证与待办

全量118项单元测试通过，0失败／错误／跳过，测试进程socket连接尝试0；原13组1818文件冻结核验通过。本轮回执见[测试结果](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/unit_test_receipt.json)、[原冻结](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/old_freeze_verification.json)。验收相关测试合计13项，其中新增3项回归覆盖嵌套null、字符串布尔值、非法身份／worksheet类型。

548个基线文件核对中，546份原工作包／数据文件保持原字节；两份实现文件（HTML模板与Python校验器）按本轮修复更新。v2独立新增4份工作包文件，v1页面／清单／空表、候选输入快照、旧QA与预测未改，详见[文件保持记录](../../ENACT/docs/WBW/evidence/acceptance_ui_interaction_20261029_v1/preservation.json)。

页面交互已经可以程序验证，不能再概括成“剩下全是人的工作”。真正的人工部分是独立事实与可判性裁决；之后仍有新候选重建、分布和基线重算、最终执行冻结。它们不由这次浏览器测试替代。

只读远端查询当前main为`4d5ec41723092a3f7aef6b06235e5504decdfe6e`，本地`fbf6585`与`150ca74`尚未在远端。本轮未尝试推送，不声称同步。原图片忽略策略保持，历史504张已跟踪图不变。
