# 04 · 实时更新

## 目标

在已有的数据库权威状态和公开事件上增加实时 UI 更新，让 Requester 与 Helper 在演示中无需手动刷新即可观察变化。

## 交付范围

- 实现 `/ws/requests/{request_id}`，推送状态变化和公开 `AgentEvent`；仅向有权查看的演示角色开放对应数据。
- 前端订阅、显示连接状态，并在断线重连后通过 HTTP GET 对齐当前权威状态。
- 对事件使用稳定 ID 或序号去重，避免重复展示；不推送隐藏推理或敏感配置。

## 完成证据

通过 [AT-12](../ACCEPTANCE_TESTS.md#04-实时更新)。WebSocket 是传输层，不拥有状态机；状态规则见 [工作流](../AGENT_WORKFLOW.md)。

下一阶段：[05 演示加固](05-demo-hardening.md)。
