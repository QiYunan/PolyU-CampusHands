# CampusHands Agent 工作流

## 分阶段启用

[第一阶段](milestones/01-mvp-foundation.md)只有结构化表单、API 和数据库闭环，不运行 Agent，也不接入真实 LLM。[第二阶段](milestones/02-borrowloop-flow.md)用确定性服务完成匹配、邀请和状态机。[第三阶段](milestones/03-agent-integration.md)在同一服务接口上加入自然语言解析、澄清、可见的 Agent 行动及 provider fallback。实时推送在 [第四阶段](milestones/04-realtime-updates.md)加入。

第二阶段仍由结构化表单提交必需字段；缺失字段返回验证错误，不启用对话澄清。Requester 在保存草稿后显式启动匹配。

## 状态机

状态由服务层唯一控制；正式请求的 `draft` 是已创建但未开始匹配的请求。第三阶段在独立 `HelpRequestDraft` 中使用 `collecting_details → ready → confirmed` 保存澄清状态，必需字段完整且经用户确认后才创建正式请求。正式请求终态为 `completed`、`cancelled`、`expired`、`failed`。

| 当前状态 | 允许的下一状态 | 触发条件 |
| --- | --- | --- |
| `draft` | `searching`, `cancelled` | Requester 明确启动匹配、用户取消；字段已在确认前校验。 |
| `searching` | `awaiting_response`, `failed`, `cancelled`, `expired` | 找到候选人并发 Offer、无可用候选人或服务错误、取消、截止时间到。 |
| `awaiting_response` | `searching`, `matched`, `cancelled`, `expired` | 拒绝/Offer 超时后继续搜索、接受、取消、请求过期。 |
| `matched` | `in_progress`, `cancelled` | 双方开始交接、Requester 取消。 |
| `in_progress` | `completed`, `cancelled` | 双方确认交接、Requester 取消。 |

任何未列出的转换都应拒绝并保留原状态。`failed` 表示本次流程无法继续且应记录可理解原因；模型或网络故障不能伪装为匹配成功。Offer 的 `pending → accepted/declined/expired` 是独立子状态，不能仅靠请求状态推断。截止时间和 Offer 响应超时分别处理。

## 一次请求的行动顺序

1. 接收请求。第三阶段由 `parse_help_request` 将自然语言映射为 `category`、`item_type`、`location`、`deadline`、`urgency`，并验证输出；第二阶段由结构化表单提供这些值。必需字段缺失时在独立草稿中提出仅针对缺失字段的澄清问题，不创建正式请求或 Offer。
2. 用户修改或确认解析字段后，用 `create_help_request` 幂等保存正式请求。服务层核验演示用户、截止时间和字段。创建成功后保持 `draft`；显式启动匹配时才进入 `searching`。
3. 调用 `search_helpers` 做物品、可用性、校内范围和时限等硬过滤，再由 `rank_candidates` 按可在截止前交接、建筑位置近远及稳定 ID 做确定性排序；无需实时地图服务。候选集、顺序和资格以数据库及规则为准，模型不能虚构。
4. 对最合适且尚未联系的候选人调用 `send_help_offer`；站内 Inbox 与数据库记录表示已发送。进入 `awaiting_response`，记录公开事件。服务层保证同一请求与帮助者的重复调用不会重复发 Offer。
5. 现有确定性服务的 `record_helper_response` 记录接受或拒绝，`check_offer_timeout` 处理到期未答。拒绝或超时后，服务自动根据剩余候选人继续搜索并联系下一位；Agent 只观察并解释结果，不选择权威候选人。接受后服务记录匹配与交接信息。
6. `start_request` 在双方开始交接时进入 `in_progress`。`complete_request` 需核验 Requester 和 Helper 各自确认；`cancel_request` 可按权限取消并释放预留物品。请求仍在寻找帮助者时，到达截止时间转为 `expired`；已匹配后不因该时间自动过期。

每一步遵循“提出动作 → 校验参数 → 调用工具 → 观察权威结果 → 选择下一步”，单次运行最多 6 个步骤和 3 次模型决策。`wait_for_response` 立即返回并终止本次运行，不保持 HTTP 请求；`finish` 仅终止 Agent loop，绝不完成真实借物任务。工具返回拒绝、冲突、超时或空候选时重读权威状态，不重复写入或假定成功。公开 `AgentEvent` 只描述可理解的动作与结果，不记录隐藏 chain-of-thought。

## 工具与信任边界

模型可提议的工具仅为 `ask_clarification`、`create_help_request`（仅确认后）、`search_helpers`、`send_help_offer`、`observe_request`、`wait_for_response`、`finish`。自然语言解析为独立模型调用。`rank_candidates`、Helper 应答、超时、状态转换、取消与双人确认仍是服务内部操作，不暴露为模型工具。DeepSeek/Ollama 优先使用相同的 native function/tool schema，必要时兼容严格验证的 JSON 动作；所有名称和参数均由本地 allowlist 与 Pydantic 校验。

Demo 结果卡片可显示 `validated_actions` 中的 `search_helpers` 或 `send_help_offer` 名称，前提是动作已通过本地校验并交给确定性服务执行。单次 Agent 运行最多接受一次只读 `search_helpers`；之后的工具列表移除它，避免模型对同一观测反复空转。被拒绝的提议、`finish`、`wait_for_response`、工具参数、模型原始响应和隐藏推理不进入该字段或公开时间线。模型由后端启动配置选定；演示中不提供公开的 provider 切换功能。真实演示优先 DeepSeek、自动 fallback 到 Ollama；明确标注的 Mock Recovery Mode 只能在计时前选择，不能冒充真实模型输出。

## 模型选择与 fallback（第三阶段）

统一 provider 接口至少涵盖离线、结果稳定的 `MockLLMProvider`，以 DeepSeek 为主的 `DeepSeekProvider`，以及本地备用 `OllamaProvider`。业务服务不直接依赖某一供应商。配置由后端环境变量提供，例如 `LLM_PRIMARY_PROVIDER`、`LLM_FALLBACK_PROVIDER`、`LLM_TIMEOUT_SECONDS`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`OLLAMA_BASE_URL` 和 `OLLAMA_MODEL`；具体模型名与能力在接入时核验。

主 provider 成功且输出通过 schema 验证时使用其结果。超时、连接失败、429、5xx、空 JSON 或 schema 错误最多安全重试一次；仍失败时尝试本地备用一次。重试只用于模型步骤，不能重放已执行的状态变更工具。备用也失败时返回可恢复错误；若业务动作已经提交，响应携带真实请求 ID 和状态供前端 GET 对齐，不回滚现实动作。CI 固定使用 Mock，不访问网络模型。普通解析和动作选择使用 non-thinking；复杂重规划才考虑 thinking，且不得保存或展示推理内容。

本地 Ollama 请求直连 loopback，不继承系统代理；解析使用 JSON Schema 输出并保持本地 Pydantic 校验。若模型漏掉输入中唯一明确的 `N分钟后`，适配层只补回该数字并再次验证 schema；含糊或多个时间仍需用户澄清。此校正不赋予模型或适配层修改业务状态的权限。
