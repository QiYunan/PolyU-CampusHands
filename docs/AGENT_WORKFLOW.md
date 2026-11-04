# CampusHands Agent 工作流

## 分阶段启用

[第一阶段](milestones/01-mvp-foundation.md)只有结构化表单、API 和数据库闭环，不运行 Agent，也不接入真实 LLM。[第二阶段](milestones/02-borrowloop-flow.md)用确定性服务完成匹配、邀请和状态机。[第三阶段](milestones/03-agent-integration.md)在同一服务接口上加入自然语言解析、澄清、可见的 Agent 行动及 provider fallback。实时推送在 [第四阶段](milestones/04-realtime-updates.md)加入。

第二阶段仍由结构化表单提交必需字段；缺失字段返回验证错误，不启用对话澄清。Requester 在保存草稿后显式启动匹配。

## 状态机

状态由服务层唯一控制；`draft` 是已创建但未开始匹配的请求，`collecting_details` 等待补充必需字段。终态为 `completed`、`cancelled`、`expired`、`failed`。

| 当前状态 | 允许的下一状态 | 触发条件 |
| --- | --- | --- |
| `draft` | `collecting_details`, `searching`, `cancelled` | 字段缺失、字段齐全后启动、用户取消。 |
| `collecting_details` | `searching`, `cancelled`, `expired` | 补齐字段、取消、截止时间到。 |
| `searching` | `awaiting_response`, `failed`, `cancelled`, `expired` | 找到候选人并发 Offer、无可用候选人或服务错误、取消、截止时间到。 |
| `awaiting_response` | `searching`, `matched`, `cancelled`, `expired` | 拒绝/Offer 超时后继续搜索、接受、取消、请求过期。 |
| `matched` | `in_progress`, `cancelled` | 双方开始交接、Requester 取消。 |
| `in_progress` | `completed`, `cancelled` | 双方确认交接、Requester 取消。 |

任何未列出的转换都应拒绝并保留原状态。`failed` 表示本次流程无法继续且应记录可理解原因；模型或网络故障不能伪装为匹配成功。Offer 的 `pending → accepted/declined/expired` 是独立子状态，不能仅靠请求状态推断。截止时间和 Offer 响应超时分别处理。

## 一次请求的行动顺序

1. 接收请求。第三阶段由 `parse_help_request` 将自然语言映射为 `category`、`item_type`、`location`、`deadline`、`urgency`，并验证输出；第二阶段由结构化表单提供这些值。必需字段缺失时提出一条针对性澄清问题，保持 `collecting_details`。
2. 用 `create_help_request` 保存请求。服务层核验当前演示用户、截止时间和字段。Milestone 01 创建成功后保持 `draft`；从 Milestone 02 启动匹配时才进入 `searching`。
3. 调用 `search_helpers` 做物品、可用性、校内范围和时限等硬过滤，再由 `rank_candidates` 按可在截止前交接、建筑位置近远及稳定 ID 做确定性排序；无需实时地图服务。候选集、顺序和资格以数据库及规则为准，模型不能虚构。
4. 对最合适且尚未联系的候选人调用 `send_help_offer`；站内 Inbox 与数据库记录表示已发送。进入 `awaiting_response`，记录公开事件。服务层保证同一请求与帮助者的重复调用不会重复发 Offer。
5. `record_helper_response` 记录接受或拒绝；`check_offer_timeout` 处理到期未答。拒绝或超时后，`expand_search` 根据剩余候选人继续搜索并联系下一位；接受后由 `mark_request_matched` 记录匹配与交接信息。
6. `start_request` 在双方开始交接时进入 `in_progress`。`complete_request` 需核验 Requester 和 Helper 各自确认；`cancel_request` 可按权限取消并释放预留物品。请求仍在寻找帮助者时，到达截止时间转为 `expired`；已匹配后不因该时间自动过期。

每一步遵循“提出动作 → 校验参数 → 调用工具 → 观察权威结果 → 选择下一步”。工具返回拒绝、冲突、超时或空候选时，先重读当前状态和已联系名单，再选择未联系的候选人或向用户说明无法继续；不得重复写入或假定成功。公开 `AgentEvent` 只描述可理解的动作与结果，不记录隐藏 chain-of-thought。

## 工具与信任边界

计划中的工具接口为 `parse_help_request`、`create_help_request`、`search_helpers`、`rank_candidates`、`send_help_offer`、`record_helper_response`、`check_offer_timeout`、`expand_search`、`mark_request_matched`、`start_request`、`complete_request`、`cancel_request`。工具暴露的是经过限制的服务操作；数据库写入、过滤排序、超时、权限、状态转换和双人完成确认始终由确定性代码负责。模型可决定澄清措辞、邀请文案和下一步建议，但不能直接修改状态或伪造事实。

## 模型选择与 fallback（第三阶段）

统一 provider 接口至少涵盖离线、结果稳定的 `MockLLMProvider`，以 DeepSeek 为主的 `DeepSeekProvider`，以及本地备用 `OllamaProvider`。业务服务不直接依赖某一供应商。配置由后端环境变量提供，例如 `LLM_PRIMARY_PROVIDER`、`LLM_FALLBACK_PROVIDER`、`LLM_TIMEOUT_SECONDS`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`OLLAMA_BASE_URL` 和 `OLLAMA_MODEL`；具体模型名与能力在接入时核验。

主 provider 成功且输出通过 schema 验证时使用其结果。超时、连接失败、429 或 5xx 最多安全重试一次；仍失败时尝试本地备用。重试只用于可重复的模型读取/生成步骤，不能重放已执行的状态变更工具。备用也失败或结果无效时返回可恢复错误，并保留数据库中的真实状态，不合成匹配结果。CI 固定使用 Mock，不访问网络模型。
