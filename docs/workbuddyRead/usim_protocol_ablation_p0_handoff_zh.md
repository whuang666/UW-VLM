# 双协议开发对照P0交付与执行入口

日期：2026-10-28（Asia/Shanghai）。本轮仅完成P0实现、离线测试和候选输入准备。**真实冒烟未运行，正式588次未启动，模型请求为0。** P1已由 `3c7cda6` 保存，本轮不重做或改写P1结果。

## 已完成

| 文件 | 职责 |
|---|---|
| `ENACT/scripts/usim/protocol_ablation_v1.py` | 离线契约、计划与请求构造、固定拼接、主副解析、输入与响应摘要 |
| `ENACT/scripts/usim/run_v02_protocol_ablation.py` | prepare／execute／analyse／verify四入口；默认prepare；仅execute读取密钥和联网 |
| `tools/verify_protocol_ablation.py` | 独立于运行器的核验入口，文件冻结和请求重建分别报告 |
| `tools/test_protocol_ablation_v1.py` | 30项P0测试，含12类负例、断点／续跑、模拟传输与stock评分器端到端检查 |
| `ENACT/docs/protocols/protocol_ablation2048_v1.md` | 新版本请求、评分、阶段冻结和错误处理契约 |

全量tools测试84项通过，0失败、0错误、0跳过；测试时拦截urllib联网，实际触发0次。原评分契约四类检查也通过，其证据写独立目录，历史契约证据未覆盖。

测试目录中的HTTP结果均由临时目录里的模拟传输生成，不是模型成绩，也没有写入生产运行目录。

## 候选计划与正确状态

生产目录：`ENACT/data/usim_enact/runs/qwen3.8-max/v02_protocol_ablation2048_dev_v1/`。

- 双协议：`no_prefill`、`prefill`；各自A/B/C=84、D=42，共588次正式逻辑请求。
- 独立兼容性冒烟为8次，不计正式分母。
- 预算2048、temperature=0、thinking=false；同题两个协议相邻调用，先后次序平衡且seed固定。
- C请求确实不含图片，D等于A的完整forward子集且沿用已冻结的去动作文本输入。
- `plan_sha256=0fc846e9dd354b5d2de62678fca072a17c5c04c460c00b2904dad8e20581f3b3`。
- `candidate.freeze.json` 文件SHA-256为 `f61d6601b646549ed6411b123eb4d9568b803006d58034bc3309ff98e1535961`。
- 候选冻结锁定源码／测试／规范、输入／图像、相关主评分代码与场景图／源帧依赖；它不是正式执行已通过的证明。
- 当前prepared_inputs核验通过，`execution_verified=false`；完整运行核验应返回exit 2，因为真实冒烟与正式预测不存在。
- 当前没有 `execution.freeze.json`，生产目录没有任何 `predictions.jsonl`。只有8次真实兼容性冒烟通过后，运行器才生成execution冻结并允许正式阶段。

本轮核验123个历史run文件前后字节未变。准备时密钥读取次数0、网络调用0，未改历史主／副冻结文件。

## 当前可运行的离线命令

```powershell
Set-Location 'E:\code\UW-VLM'
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$p0Run = 'ENACT/data/usim_enact/runs/qwen3.8-max/v02_protocol_ablation2048_dev_v1'

# 默认行为也是prepare；已有候选文件只核验，不覆盖
& $py ENACT/scripts/usim/run_v02_protocol_ablation.py --prepare

# 只核验准备状态，不宣称执行通过
& $py tools/verify_protocol_ablation.py --run-dir $p0Run --prepared-only
& $py ENACT/scripts/usim/run_v02_protocol_ablation.py --verify --prepared-only

# 当前应为exit 2：完整运行证据尚未形成。这是明确的未通过，不能忽略返回码
& $py tools/verify_protocol_ablation.py --run-dir $p0Run

# 当前analyse也应拒绝不完整运行，不产生模型成绩
& $py ENACT/scripts/usim/run_v02_protocol_ablation.py --analyse

# 测试：所有新增HTTP路径在测试中使用模拟传输
& $py -m unittest discover -s tools -p 'test_*.py' -v
```

## 后续付费执行阶段的命令（本轮未运行）

```powershell
# 显式执行8次兼容性冒烟；全部通过才生成execution冻结
& $py ENACT/scripts/usim/run_v02_protocol_ablation.py --execute --smoke-only

# 接续同一计划的588次正式请求；保留已尝试的终态结果
& $py ENACT/scripts/usim/run_v02_protocol_ablation.py --execute --resume

# 完整证据核验，再生成stock主评分与副指标全题报告
& $py tools/verify_protocol_ablation.py --run-dir $p0Run
& $py ENACT/scripts/usim/run_v02_protocol_ablation.py --analyse
```

若直接使用 `--execute`，运行器也按冒烟→execution冻结→正式的顺序执行。没有已校验的候选输入或冒烟不通过，正式请求被阻止。已有证据必须显式resume，不能覆盖已失败、截断或不合规回答。

## 核验／退出码

- prepared_inputs：只证明当前源码和准备输入一致，明确 `execution_verified=false`。
- complete_run：默认严格范围。每单元ID集、请求数、所有尝试和响应、固定拼接及重新解析全部符合才通过；0条请求不能通过。
- 部分证据核验只在运行器内部用于安全续跑，不作为完整结果通过的证明。
- exit 0：所请求的操作成功；具体范围必须看scope，prepare不是完整执行。
- exit 2：冻结、完整性、兼容性、CLI或资产等条件失败／未满足，停止相应操作。
- exit 3：正式执行证据完整，但候选预填协议未通过严格格式gate。无预填控制的格式失败继续保留在分母。

## 重试与中断边界

仅网络错误和已声明暂时性HTTP状态最多尝试3次，记录每一次原始响应；200下的格式错误、答错和截断不重试。400/401/403/404/422停止整个运行。

每次发送前写inflight标记。若进程在HTTP边界被中断，未决标记／孤立响应会阻止自动重发，需先按证据恢复裁决；不能以“没有最终预测行”为由盲目再次收费请求。已有终态ID在resume时跳过，即使它记0。

旧 `tools/verify_prefill_freeze.py` 保留作为历史诊断材料，不能用于新矩阵准入。新核验器不会以请求摘要匹配抵消源文件changed，也不会声称客户端摘要就是服务端独立证明。

## 复核证据

`ENACT/docs/WBW/evidence/protocol_ablation_p0_20261028/`：

- `test_results.txt`、`test_receipt.json`：84项测试、30项P0测试ID、源文件哈希与网络拦截计数。
- `primary_contract_check.json`：原评分契约四类检查。
- `prepare_console.txt`、`offline_preparation_receipt.json`：588＋8计划、准备／完整核验范围、123个历史run文件哈希与0调用证明。
- `negative_coverage.json`：12类负例与通过的测试ID映射。

P0完成不代表P2／P3已执行，后续统计效应分析和test标注／独立验收仍按长计划推进。最终test协议与统一预算不在本次候选冻结中。
