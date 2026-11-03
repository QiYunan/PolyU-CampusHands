# 01 · MVP 基础闭环

## 目标

只交付可运行的 **前端 → FastAPI → SQLite → 前端** 持久化闭环。此阶段不接入真实 LLM，也不运行 Agent 或 MockLLM；其余能力按后续里程碑推进。

## 交付范围

- 建立最小 `frontend/` 与 `backend/` 工程、数据库连接和演示 Alice 身份；保留现有文件及用户改动。
- Requester 结构化表单提交物品类型、地点、截止时间及可选描述。后端校验并保存 `User`/`HelpRequest`，初始状态 `draft`。
- 页面按服务端 ID 重新读取请求并显示持久化状态；提供健康检查、基础错误提示和本地启动说明。
- 只实现 [架构](../ARCHITECTURE.md)中标为 01 的 HTTP 接口及相应基础检查。

## 完成证据

通过 [AT-01 至 AT-03](../ACCEPTANCE_TESTS.md#01-基础闭环)：创建、GET、刷新、重启后持久化；无效输入不入库；不需要任何 LLM 服务或密钥。

下一阶段：[02 BorrowLoop 流程](02-borrowloop-flow.md)。
