# ENACT × USIM API 方案重写记录

日期：2026-10-24（Asia/Shanghai）。本轮按用户提供的 DashScope 配置重写后续流程，交付 [WBR 完整实施方案](../WBR/ENACT-USIM-DashScope-API完整实施方案-20261024.md)。

## 本轮完成

- 方案固定完整请求地址 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，模型 `qwen3.8-max`，密钥仅以环境变量 `VLM_API_KEY` 读取，不在文档中复制其值。
- 核对当前 `scripts/usim/run_inference.py`：现有 `--base-url` 会追加 `/chat/completions`，默认 API key 为 `EMPTY`；尚不自动读取本轮三项环境变量，也不设置思考模式或完整保留响应/usage。新方案把这些列为接入改造项。
- 查阅阿里云官方视觉理解与兼容接口文档，确认公开示例包含 `qwen3.8-max` 图像请求、支持多图与 Base64 Data URL，并说明 Qwen3.8 默认开启思考。方案显式固定 `enable_thinking=false` 为首轮条件，思考模式另做对照。
- 完整写明单题四图预检、固定分母修复、独立标签复核、四组分层 20 题试跑、全量评测、视觉对照、有限重试、续跑校验、usage/费用记录和最终测试冻结。

## 本轮验证与未执行部分

| 项目 | 状态 |
|---|---|
| 本地脚本与已有试点证据核对 | 已完成，沿用 [上一轮实际审计](evidence/trial_audit_20261024.json)，本轮未重跑基线 |
| 官方公开文档读取 | 已完成，见 [摘录与响应哈希](evidence/dashscope_official_docs_20261024.json) |
| 密钥鉴权、该账户模型权限及配额 | 未发起请求，待单题预检 |
| 真实多图模型回答与成绩 | 本轮未生成 |
| runner、评分器、重试与恢复改造 | 方案已明确接口与验收，代码尚未修改 |
| 独立标签复核、裁剪/去图对照 | 待执行 |

公开文档依据：[视觉理解](https://help.aliyun.com/zh/model-studio/vision)、[兼容 Chat Completions 接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)，读取日期均为 2026-10-24。它们证明公开能力与参数说明，不证明当前密钥已成功调用；后续所有实际调用结果应单独追加执行文档。
