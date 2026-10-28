# extractable_permutation_v1 补充分析协议

版本：`extractable_permutation_v1`。冻结编号：`20261028_extractable_v1`。
本协议冻结补充解析规则、实现、所调用的主解析器与测试清单；主指标继续使用 `usim_strict_v0.3`。

## 适用范围与时间边界

规则来源于开发阶段诊断。已有 dev256 和 diag1024 响应上的分析始终属于**事后探索**。冻结现在的规则不会使这些历史结果成为事前实验，也不是外部注册平台上的预注册。

本次不冻结最终 test 的标签、题集、图片、模型快照、提示或解码参数。当前 1024-token 诊断仍为 `fail_on_fixed_subset`；统一预算尚未选定。副指标不改变原预算判据。最终 test 必须在这些剩余项目独立冻结后运行，不得按 test 表现修改本规则。

## 规范

1. 资格：输入记录必须存在，且 `status == "success"`、`finish_reason == "stop"`。缺失、失败、其他状态或停止原因一律计 0。调用方先检查成功状态；提取函数的签名只接收正文、停止原因和期望长度。
2. 外层：正文中恰好只有一个 `[` 和一个 `]`，构成唯一候选列表。列表之后只能有空白。英文句号、全角句号、引号、代码围栏或说明文字均不容忍；多余、嵌套或未闭合的方括号不允许被跳过。
3. 内层：候选完整字符串直接交给现有 `USIMEvaluator.parse_strict`，不复制一份值检查实现。整数、布尔值拒绝、长度、范围、重复项及排列校验均使用主解析器的判定。
4. 长度：若题目有 `num_states = L` 个状态，期望长度为 `L - 1`，排列域为 `1..(L-1)`。提取过程不读取 gt。分析层校验题目结构及 gt 长度一致，提取结束后才用 gt 判断答对。
5. 歧义：出现多个方括号候选时直接计 0，不选择最后一个、最像答案的一个或与 gt 相等的一个。
6. 分母：采用完整冻结 QA 集合。缺失响应继续计 0；缺失评分条目、重复／未知 ID、QA 哈希或参考答案冲突导致分析报错，不能缩小分母。
7. 对称性：所有条件使用同一规则。同时报告主指标的严格合法率、可提取率、`EM_extractable = 提取后答对题数 / 全部题数` 及失败原因。可提取但答错的答案仍计入可提取数，其 EM 为 0。条件于可提取子集的准确率只能作为带分母的辅助描述。

提取函数：`extract(text, finish_reason, expected_length)`；签名中无 gt。
冻结前修复了初稿遗漏的畸形括号与成功状态校验；该修复未改变已有 326 条响应上的可提取计数。

## 核验与复现

在仓库根目录运行：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'

# 只读核验源码、规则、测试清单和整个清单的哈希
& $py ENACT/scripts/usim/freeze_extractable_v1.py --verify ENACT/docs/protocols/extractable_permutation_v1.freeze.json

# 全量单元测试
& $py -m unittest discover -s tools -p 'test_*.py' -v

# 现有开发诊断上的事后分析；frozen=true 只表示规则已核验
& $py ENACT/scripts/usim/report_extractable_v1.py `
    --run-dir ENACT/data/usim_enact/runs/qwen3.8-max/v02_budget1024_diag_v1 `
    --condition A=A_full_image --condition B=B_zoom `
    --protocol-freeze ENACT/docs/protocols/extractable_permutation_v1.freeze.json
```

冻结清单记录规则文本、模块、分析入口、原评分器、冻结工具和三份相关测试文件的 SHA-256，以及成功运行的完整测试数和补充规则测试 ID。创建命令为 `freeze_extractable_v1.py`（不带 `--verify`），它先运行测试再以独占方式创建清单；已有清单不能覆盖。

冻结后任何行为变更，包括标点容忍，均需独立版本与新清单，并保留本版。旧主协议、原始预测和评分报告不覆盖。
