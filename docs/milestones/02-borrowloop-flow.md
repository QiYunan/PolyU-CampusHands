# 02 · BorrowLoop 确定性流程

## 目标

在 [01 基础闭环](01-mvp-foundation.md)上完成站内借物匹配、邀请、拒绝/超时后的下一候选人、接受及双人交接确认。所有决策与状态变更由确定性服务执行，尚不要求模型参与。

## 交付范围

- 扩展 `UserItem`、`HelpOffer`、`AgentEvent` 和可重复 seed：Alice 请求，Bob 与 Carol 有科学计算器，David 只有 USB-C 充电器。Bob 拒绝、Carol 接受是演示动作，不预置为已发生的数据库事实。
- 建立 [状态机和工具服务](../AGENT_WORKFLOW.md)，实现硬过滤、稳定排序、Offer 超时、重复调用幂等及请求取消。
- 建立 Helper Inbox、Demo 角色切换和公开操作时间线；用站内记录模拟通知。
- 实现 [架构](../ARCHITECTURE.md#api-边界与交付阶段)标为 02 的接口，包括原始清单未覆盖的 Helper 交接确认。

## 完成证据

通过 [AT-04 至 AT-08](../ACCEPTANCE_TESTS.md#02-borrowloop-确定性流程)。现阶段页面可用 HTTP 拉取状态，实时推送留待 [04](04-realtime-updates.md)。

下一阶段：[03 Agent 接入](03-agent-integration.md)。
