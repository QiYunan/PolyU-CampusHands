# 04 · 实时更新

## 目标

在已有的数据库权威状态和公开事件上增加实时 UI 更新，让 Requester 与 Helper 在演示中无需手动刷新即可观察变化。

## 交付范围

- 实现 `/ws/requests/{request_id}` 与 `/ws/helpers/{helper_id}/offers`，分别发送公开请求事件和仅属于该 Helper 的 Inbox 通知；握手前核对 Demo 角色权限与本地 Origin。
- 只从已提交的 `AgentEvent` 按全局 ID 顺序发送通知；连接失败不影响业务事务或其他客户端。
- 前端先 GET、订阅成功后再 GET，显示连接状态；断线时两秒 HTTP 轮询并指数退避重连。
- 对事件使用稳定 ID 或序号去重，避免重复展示；不推送隐藏推理或敏感配置。

## 完成证据

通过 [AT-12](../ACCEPTANCE_TESTS.md#04-实时更新)。WebSocket 是传输层，不拥有状态机；状态规则见 [工作流](../AGENT_WORKFLOW.md)。

下一阶段：[05 演示加固](05-demo-hardening.md)。
