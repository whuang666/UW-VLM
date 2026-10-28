# 双协议2048开发对照：主副指标与episode配对分析

全部结果为dev；8次冒烟不计入分母。预填是明确的请求协议因素。

| 协议/条件 | N | episode | 严格合法 | 截断 | EM | TA | PA_item | PA_micro | 副指标全题EM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_prefill/A | 84 | 19 | 84 | 0 | 0.9167 | 0.9167 | 0.9425 | 0.9404 | 0.9167 |
| no_prefill/B | 84 | 19 | 81 | 0 | 0.9048 | 0.9048 | 0.9246 | 0.9174 | 0.9167 |
| no_prefill/C | 84 | 19 | 84 | 0 | 0.6071 | 0.6071 | 0.6518 | 0.6147 | 0.6071 |
| no_prefill/D | 42 | 19 | 42 | 0 | 0.6429 | 0.6429 | 0.6825 | 0.6606 | 0.6429 |
| prefill/A | 84 | 19 | 84 | 0 | 0.9286 | 0.9286 | 0.9504 | 0.9495 | 0.9286 |
| prefill/B | 84 | 19 | 84 | 0 | 0.9048 | 0.9048 | 0.9425 | 0.9404 | 0.9048 |
| prefill/C | 84 | 19 | 84 | 0 | 0.5714 | 0.5714 | 0.6190 | 0.5872 | 0.5714 |
| prefill/D | 42 | 19 | 42 | 0 | 0.6429 | 0.6429 | 0.6706 | 0.6422 | 0.6429 |

## 协议效应：预填减无预填

episode配对bootstrap 10,000次；区间为95%百分位区间，未据显著性选择报告。

| 条件 | N | 严格ΔEM [CI] | 副指标ΔEM [CI] | 仅预填对 | 仅无预填对 | 两侧可提取 | 排列一致 |
|---|---:|---|---|---:|---:|---:|---:|
| A | 84 | +0.0119 [+0.0000, +0.0333] | +0.0119 [+0.0000, +0.0333] | 1 | 0 | 84 | 83 |
| B | 84 | +0.0000 [-0.0513, +0.0435] | -0.0119 [-0.0556, +0.0263] | 2 | 2 | 82 | 80 |
| C | 84 | -0.0357 [-0.0833, +0.0135] | -0.0357 [-0.0833, +0.0135] | 1 | 4 | 84 | 74 |
| D | 42 | +0.0000 [-0.0698, +0.0714] | +0.0000 [-0.0698, +0.0714] | 1 | 1 | 42 | 40 |

## 输入效应：同协议比较

| 协议 | 比较 | 共同N | ΔEM [CI] | 副指标ΔEM [CI] |
|---|---|---:|---|---|
| no_prefill | A-B | 84 | +0.0119 [-0.0278, +0.0500] | +0.0000 [-0.0455, +0.0455] |
| no_prefill | A-C | 84 | +0.3095 [+0.1842, +0.4271] | +0.3095 [+0.1842, +0.4271] |
| no_prefill | A-D | 42 | +0.1905 [+0.0513, +0.3261] | +0.1905 [+0.0513, +0.3261] |
| prefill | A-B | 84 | +0.0238 [+0.0000, +0.0556] | +0.0238 [+0.0000, +0.0556] |
| prefill | A-C | 84 | +0.3571 [+0.2343, +0.4773] | +0.3571 [+0.2343, +0.4773] |
| prefill | A-D | 42 | +0.2143 [+0.0278, +0.3750] | +0.2143 [+0.0278, +0.3750] |

## 用量与延迟

latency为单逻辑请求从第一次开始到末次结束，含重试等待，不含请求间1秒限速。

| 协议/条件 | HTTP尝试 | 输入tokens | 输出tokens | 输出最大 | 延迟中位s | 延迟P95s |
|---|---:|---:|---:|---:|---:|---:|
| no_prefill/A | 84 | 60658 | 738 | 13 | 2.244 | 3.688 |
| no_prefill/B | 84 | 84818 | 3024 | 1971 | 2.699 | 5.239 |
| no_prefill/C | 84 | 34802 | 654 | 12 | 1.004 | 1.313 |
| no_prefill/D | 42 | 26032 | 369 | 13 | 2.270 | 2.966 |
| prefill/A | 84 | 60742 | 654 | 12 | 2.245 | 3.617 |
| prefill/B | 84 | 84902 | 654 | 12 | 2.591 | 5.721 |
| prefill/C | 84 | 34886 | 570 | 11 | 1.051 | 1.609 |
| prefill/D | 42 | 26074 | 327 | 12 | 2.122 | 3.167 |

## 方向、长度与文本基线分层

程序文本基线答对/答错是基线行为，不表示题目对所有文本方法可解/不可解。

| 协议/条件 | 分层 | N | 严格EM | 副指标全题EM |
|---|---|---:|---:|---:|
| no_prefill/A | setting=forward_L3 | 19 | 0.8947 | 0.8947 |
| no_prefill/A | setting=forward_L4 | 21 | 0.7619 | 0.7619 |
| no_prefill/A | setting=forward_L5 | 2 | 1.0000 | 1.0000 |
| no_prefill/A | setting=inverse_L3 | 19 | 1.0000 | 1.0000 |
| no_prefill/A | setting=inverse_L4 | 21 | 1.0000 | 1.0000 |
| no_prefill/A | setting=inverse_L5 | 2 | 1.0000 | 1.0000 |
| no_prefill/A | prior_correct=False | 29 | 0.7931 | 0.7931 |
| no_prefill/A | prior_correct=True | 55 | 0.9818 | 0.9818 |
| no_prefill/B | setting=forward_L3 | 19 | 0.8947 | 0.8947 |
| no_prefill/B | setting=forward_L4 | 21 | 0.7619 | 0.7619 |
| no_prefill/B | setting=forward_L5 | 2 | 0.5000 | 1.0000 |
| no_prefill/B | setting=inverse_L3 | 19 | 1.0000 | 1.0000 |
| no_prefill/B | setting=inverse_L4 | 21 | 1.0000 | 1.0000 |
| no_prefill/B | setting=inverse_L5 | 2 | 1.0000 | 1.0000 |
| no_prefill/B | prior_correct=False | 29 | 0.7241 | 0.7586 |
| no_prefill/B | prior_correct=True | 55 | 1.0000 | 1.0000 |
| no_prefill/C | setting=forward_L3 | 19 | 0.5263 | 0.5263 |
| no_prefill/C | setting=forward_L4 | 21 | 0.1905 | 0.1905 |
| no_prefill/C | setting=forward_L5 | 2 | 0.0000 | 0.0000 |
| no_prefill/C | setting=inverse_L3 | 19 | 1.0000 | 1.0000 |
| no_prefill/C | setting=inverse_L4 | 21 | 0.8571 | 0.8571 |
| no_prefill/C | setting=inverse_L5 | 2 | 0.0000 | 0.0000 |
| no_prefill/C | prior_correct=False | 29 | 0.1379 | 0.1379 |
| no_prefill/C | prior_correct=True | 55 | 0.8545 | 0.8545 |
| no_prefill/D | setting=forward_L3 | 19 | 0.7368 | 0.7368 |
| no_prefill/D | setting=forward_L4 | 21 | 0.6190 | 0.6190 |
| no_prefill/D | setting=forward_L5 | 2 | 0.0000 | 0.0000 |
| no_prefill/D | prior_correct=False | 29 | 0.4828 | 0.4828 |
| no_prefill/D | prior_correct=True | 13 | 1.0000 | 1.0000 |
| prefill/A | setting=forward_L3 | 19 | 0.8947 | 0.8947 |
| prefill/A | setting=forward_L4 | 21 | 0.8095 | 0.8095 |
| prefill/A | setting=forward_L5 | 2 | 1.0000 | 1.0000 |
| prefill/A | setting=inverse_L3 | 19 | 1.0000 | 1.0000 |
| prefill/A | setting=inverse_L4 | 21 | 1.0000 | 1.0000 |
| prefill/A | setting=inverse_L5 | 2 | 1.0000 | 1.0000 |
| prefill/A | prior_correct=False | 29 | 0.7931 | 0.7931 |
| prefill/A | prior_correct=True | 55 | 1.0000 | 1.0000 |
| prefill/B | setting=forward_L3 | 19 | 0.8947 | 0.8947 |
| prefill/B | setting=forward_L4 | 21 | 0.7619 | 0.7619 |
| prefill/B | setting=forward_L5 | 2 | 1.0000 | 1.0000 |
| prefill/B | setting=inverse_L3 | 19 | 1.0000 | 1.0000 |
| prefill/B | setting=inverse_L4 | 21 | 0.9524 | 0.9524 |
| prefill/B | setting=inverse_L5 | 2 | 1.0000 | 1.0000 |
| prefill/B | prior_correct=False | 29 | 0.7586 | 0.7586 |
| prefill/B | prior_correct=True | 55 | 0.9818 | 0.9818 |
| prefill/C | setting=forward_L3 | 19 | 0.3684 | 0.3684 |
| prefill/C | setting=forward_L4 | 21 | 0.1905 | 0.1905 |
| prefill/C | setting=forward_L5 | 2 | 0.0000 | 0.0000 |
| prefill/C | setting=inverse_L3 | 19 | 1.0000 | 1.0000 |
| prefill/C | setting=inverse_L4 | 21 | 0.8571 | 0.8571 |
| prefill/C | setting=inverse_L5 | 2 | 0.0000 | 0.0000 |
| prefill/C | prior_correct=False | 29 | 0.0345 | 0.0345 |
| prefill/C | prior_correct=True | 55 | 0.8545 | 0.8545 |
| prefill/D | setting=forward_L3 | 19 | 0.7895 | 0.7895 |
| prefill/D | setting=forward_L4 | 21 | 0.5714 | 0.5714 |
| prefill/D | setting=forward_L5 | 2 | 0.0000 | 0.0000 |
| prefill/D | prior_correct=False | 29 | 0.4828 | 0.4828 |
| prefill/D | prior_correct=True | 13 | 1.0000 | 1.0000 |

## 解读边界

- No causal guarantee for an alias-model snapshot
- No equivalence conclusion from nonsignificance
- Secondary metric is not pure perception accuracy
- All formal requests remain in metric denominators
- Smoke records excluded from all formal scores
- Small number of episodes; long L5 strata are particularly sparse

全部episode/任务分层、精确计数与未舍入区间见JSON。不得把未显著解释为等价，或把外显token减少解释为内部推理消失。
