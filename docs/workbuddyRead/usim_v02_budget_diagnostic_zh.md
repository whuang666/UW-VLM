# USIM v0.2 A/B 输出预算诊断 v1

日期：2026-10-28（Asia/Shanghai）。本轮准备独立开发诊断；尚未发送模型请求。

## 固定范围

新 run：`ENACT/data/usim_enact/runs/qwen3.8-max/v02_budget1024_diag_v1/`。
默认执行只做准备和离线预检，显式传 `--run` 才发送请求。

| 方向 | L3 | L4 | L5 | 题数 |
|---|---:|---:|---:|---:|
| forward | 4 | 4 | 2 | 10 |
| inverse | 2 | 2 | 2 | 6 |

共 16 道题、13 条 episode，每个条件 62 张输入图像、46 个参考转移。
A/B 同题、同 ID、同显示顺序，共 **32 次逻辑请求**。沿用原运行至多三次传输尝试的策略，HTTP 尝试上限 96；不因答案错误、格式失败或截断重试。

以原 dev 输入为候选，seed=20261028，按表中方向、L 的顺序选题；每次优先选择此前入选题数最少的 episode，再按 `SHA256(seed:ID)` 排序。选题不读取 gt、旧答案、旧成绩或旧停止原因；L5 每个方向仅两题，全部纳入。完整 ID、QA／图像／源码／旧运行来源哈希保存在新 run 的 `plan.json`。

## 参数与判据

沿用 `v02_dev_001` 的模型别名、接口、题干、无 system message 策略、格式指令、thinking=false、temperature=0、timeout=180 秒、sleep=1 秒；仅输出预算改为 1024。原 `run_inference.py`、评分器及其依赖保持原哈希。

预算通过条件：两个条件都收到完整 16 个正常停止的回答，零 `length`、零缺失／传输失败，严格格式合法率 100%。**不使用 EM 来选择预算**。评分报告另行保存；格式错误仍按原严格契约记 0。

离线摘要同时列出旧 256-token 运行在这 16 题上的格式和停止统计。该旧子集 B 有 4 条截断，其余 12 条格式合法；A 16 条全部合法。这是选题冻结后的描述，不是选题条件。新 1024-token 结果当前为 pending，离线 oracle 分数不是模型成绩。

小样本通过只支持当前子集，不能保证全量无截断。旧 256-token 响应与新响应并非同期对照，`qwen3.8-max` 也不是不可变快照，因此不能把差异全部归因于预算。如要发布新版四条件表，应另起同预算的 A/B/C/D 全量 run。

## Windows 凭据

按用户要求，`VLM_API_KEY` 已保存至 Windows 当前用户的持久环境变量。原 `.env` 未改写；工作区和诊断产物不保存密钥值。

新诊断入口优先使用进程环境；若已打开的应用持有旧环境，则只读取 Windows `HKCU\Environment` 中具名的 `VLM_API_KEY` 并传入推理子进程。不会输出密钥。通用推理入口仍保持冻结源码；从旧 PowerShell 直接调用时，先执行：

```powershell
if ([string]::IsNullOrWhiteSpace($env:VLM_API_KEY)) {
    $env:VLM_API_KEY = [Environment]::GetEnvironmentVariable('VLM_API_KEY', 'User')
}
```

## 执行

在仓库根目录：

```powershell
$py = 'C:\Users\whuang\.workbuddy\binaries\python\envs\default\Scripts\python.exe'

# 离线准备：冻结核验、资产检查、A/B dry-run、严格评分 oracle
& $py ENACT/scripts/usim/run_v02_budget_diagnostic.py

# 执行已固定的 32 次逻辑请求并评分
& $py ENACT/scripts/usim/run_v02_budget_diagnostic.py --run

# 仅继续尚未尝试的 ID；保留已失败、截断和格式错误的答案
& $py ENACT/scripts/usim/run_v02_budget_diagnostic.py --run --resume
```

输入或源码改变后拒绝沿用原 plan，必须单独版本化。旧 run、冻结文件和原始回答均不覆盖。`_preflight/` 使用占位凭据运行 dry-run、以 gt 做 oracle 测试，全部为离线检查，不证明鉴权有效。

## 本轮检查

tools 单元测试 14 项通过；原评分契约检查通过（证据重定向至临时目录）；完整 1818 文件冻结核验通过；A/B 的 16 题 oracle 和 dry-run 均通过。已验证诊断入口可从持久变量读取密钥，并使推理子进程继承；本轮网络请求数为 0。
