# 03 · Agent 接入

## 目标

在确定性 BorrowLoop 服务上加入自然语言解析、澄清、工具调用及模型失败恢复，使 Agent 能按 [工作流](../AGENT_WORKFLOW.md)观察结果并选择下一步。

## 交付范围

- 先接入离线且可重复的 `MockLLMProvider`，让演示与 CI 稳定覆盖解析、澄清和工具编排。
- 再通过统一接口接入 DeepSeek 主 provider 与 Ollama 本地备用；模型配置和 key 只存在于后端环境，示例配置不含真实密钥。
- 对模型结果和工具参数进行 schema 校验；实现安全重试一次、备用切换及双失败时的可恢复错误。
- Requester 增加自然语言入口和澄清交互；System Status 只显示 provider 类别与状态。
- 不完整输入保存在独立 `HelpRequestDraft`；用户确认后才创建正式 `HelpRequest(draft)`。Agent 使用受限工具建议动作，拒绝或超时后的下一候选人仍由第二阶段服务自动联系。`finish` 只结束 Agent loop，`wait_for_response` 非阻塞。

## 完成证据

通过 [AT-09 至 AT-11](../ACCEPTANCE_TESTS.md#03-agent-与模型)。具体模型名称、结构化输出与 tool call 能力在接入时核验；能力不支持时通过受验证的服务接口完成相同流程，不放宽确定性边界。

开发机上以虚构输入完成 DeepSeek 解析及原生 tool calling、Ollama 解析及原生 tool calling、主服务连接失败后转 Ollama 的 smoke test；未执行模型建议的业务工具。密钥轮换与离线脱敏回归状态见 [项目状态](../PROJECT_STATUS.md)。

下一阶段：[04 实时更新](04-realtime-updates.md)。
