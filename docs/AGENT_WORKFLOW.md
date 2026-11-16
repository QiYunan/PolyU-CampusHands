# CampusHands Agent 工作流

## 分阶段启用

[第一阶段](milestones/01-mvp-foundation.md)只有结构化表单、API 和数据库闭环，不运行 Agent，也不接入真实 LLM。[第二阶段](milestones/02-borrowloop-flow.md)用确定性服务完成匹配、邀请和状态机。[第三阶段](milestones/03-agent-integration.md)在同一服务接口上加入自然语言解析、澄清、可见的 Agent 行动及 provider fallback。实时推送在 [第四阶段](milestones/04-realtime-updates.md)加入。

第二阶段仍由结构化表单提交必需字段；缺失字段返回验证错误，不启用对话澄清。Requester 在保存草稿后显式启动匹配。

## 状态机

状态由服务层唯一控制；正式请求的 `draft` 是已创建但尚未发布的请求。第三阶段在独立 `HelpRequestDraft` 中使用 `collecting_details → ready → confirmed` 保存澄清状态，必需字段完整且经用户确认后才创建正式请求。新流程中 `awaiting_response` 表示已发布、等待 Helper 自主认领；不再表示某一名 Helper 持有待答邀请。旧 `searching` 和 `failed` 仅用于历史记录兼容，不进入新的发布和认领主流程。

| 当前状态 | 允许的下一状态 | 触发条件 |
| --- | --- | --- |
| `draft` | `awaiting_response`, `cancelled`, `expired` | Requester 原子确认当前完整表单后，由受控 Agent／结构化 API 发布，或取消／到期。 |
| `searching` | `awaiting_response`, `failed`, `cancelled`, `expired` | 历史状态；新请求不经过它。 |
| `awaiting_response` | `matched`, `cancelled`, `expired` | 首个有效 Helper 原子认领、Requester 取消或截止时间到；不设个人邀请超时。 |
| `matched` | `in_progress`, `cancelled` | 双方开始交接、Requester 取消。 |
| `in_progress` | `completed`, `cancelled` | 双方确认交接、Requester 取消。 |

任何未列出的转换都应拒绝并保留原状态。直接满足或已允许的替代响应创建唯一 `accepted` HelpOffer；`ask_before_substitute` 的不匹配响应创建 `proposed` Offer，但请求继续保持 `awaiting_response`，Alice 接受某个提案后才进入 `matched`。新流程没有 `pending` Offer，也不会因无人点击而进入 `failed`。即使当前无人响应，已发布请求仍开放到成功认领、取消或截止时间；模型或网络故障不能伪装为匹配成功。

## 一次请求的行动顺序

1. 接收请求。模型将自然语言映射为 `category`、用户可核对的 `need_summary`、可选 `item_type`、地点、截止时间和紧急程度；未知物品与服务使用内部 `other`。品牌／型号只从借物原文提取，只有用户明确表达“只接受／不能替代”时才提取 `exact_only`。必需字段是 `need_summary`、`location`、`deadline`；服务请求不追问物品类型。
2. 用户在解析结果中修改字段后，只点击一次“确认并创建请求”。前端把当前完整表单作为 confirm payload；服务在同一个 `BEGIN IMMEDIATE` 事务中应用字段、重新验证并幂等创建正式 `draft`，不能确认旧的服务器草稿。创建请求本身不创建 Offer。
3. `search_helpers` 仅保留为不暴露 Helper 数据的安全预检；它不再检查库存、Helper 位置、available 状态、步行时间或信誉。地点 registry 只校验 Requester 的交接地点。模型看不到 Helper 身份、库存或内部字段。
4. 模型可提出受限 `publish_request(request_id)`；服务核验请求归属、状态、地点和截止时间后转为 `awaiting_response` 并写入公开事件。不接受模型指定 Helper／Item ID、能力确认或发布文案。重复调用不会重复发布。
5. 所有 Demo Helper 同时看到全部开放请求，广场只按紧急程度、截止时间、发布时间和稳定 ID 排序。点击“我可以帮助”后，Helper 必须确认能在截止前完成，可填写帮助说明；借物时可填写实际品牌／型号。服务在事务内复核开放、未过期、非本人请求、能力确认、品牌规则和唯一认领，不读取预设 `UserItem` 或位置作为资格。首个有效直接响应创建 `accepted` Offer；其他并发直接响应得到安全 409。
6. `exact_only` 的不匹配响应被拒绝；`ask_before_substitute` 的不匹配响应创建 `proposed` Offer，等待 Alice 接受或拒绝；`equivalent_ok` 的已确认替代响应可直接认领。提案接受前请求不匹配且仍可收到其他响应；接受时再次原子检查并取消其他提案。
7. `start_request` 在双方开始交接时进入 `in_progress`。`complete_request` 核验 Requester 和成功响应的 Helper 各自确认；取消、到期和完成均允许 Offer 没有 `item_id`。开放请求到达截止时间转为 `expired`；已匹配后不因该时间自动过期。

每一步遵循“提出动作 → 校验参数 → 调用工具 → 观察权威结果 → 选择下一步”，单次运行最多 6 个步骤和 3 次模型决策。`wait_for_response` 立即返回并终止本次运行，不保持 HTTP 请求；`finish` 仅终止 Agent loop，绝不完成真实借物任务。工具返回拒绝、冲突、超时或空候选时重读权威状态，不重复写入或假定成功。公开 `AgentEvent` 只描述可理解的动作与结果，不记录隐藏 chain-of-thought。

## 工具与信任边界

模型可提议的工具仅为 `ask_clarification`、`create_help_request`（仅确认后）、`search_helpers`、`publish_request`、`observe_request`、`wait_for_response`、`finish`。自然语言解析为独立模型调用。Helper 的现实能力确认、品牌规则、提案接受、广场排序、原子认领、状态转换、取消与双人确认仍是服务内部操作，不暴露为模型工具。DeepSeek/Ollama 优先使用相同的 native function/tool schema，必要时兼容严格验证的 JSON 动作；所有名称和参数均由本地 allowlist 与 Pydantic 校验。

旧请求可能仍带有早期 `matching_issue` 代码，API 为历史兼容继续读取；新自主响应主流程只在草稿阶段处理不可识别地点，不再根据库存、availability 或步行时间生成资格问题。恢复操作见 [Milestone 06](milestones/06-matching-quality.md)。

Demo 结果卡片可显示 `validated_actions` 中的 `search_helpers` 或 `publish_request` 名称，前提是动作已通过本地校验并交给确定性服务执行。单次 Agent 运行最多接受一次只读 `search_helpers`；之后的工具列表移除它，避免模型对同一观测反复空转。被拒绝的提议、`finish`、`wait_for_response`、工具参数、模型原始响应和隐藏推理不进入该字段或公开时间线。模型由后端启动配置选定；演示中不提供公开的 provider 切换功能。真实演示优先 DeepSeek、自动 fallback 到 Ollama；明确标注的 Mock Recovery Mode 只能在计时前选择，不能冒充真实模型输出。

## 模型选择与 fallback（第三阶段）

统一 provider 接口至少涵盖离线、结果稳定的 `MockLLMProvider`，以 DeepSeek 为主的 `DeepSeekProvider`，以及本地备用 `OllamaProvider`。业务服务不直接依赖某一供应商。配置由后端环境变量提供，例如 `LLM_PRIMARY_PROVIDER`、`LLM_FALLBACK_PROVIDER`、`LLM_TIMEOUT_SECONDS`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`OLLAMA_BASE_URL` 和 `OLLAMA_MODEL`；具体模型名与能力在接入时核验。

主 provider 成功且输出通过 schema 验证时使用其结果。超时、连接失败、429、5xx、空 JSON 或 schema 错误最多安全重试一次；仍失败时尝试本地备用一次。重试只用于模型步骤，不能重放已执行的状态变更工具。备用也失败时返回可恢复错误；若业务动作已经提交，响应携带真实请求 ID 和状态供前端 GET 对齐，不回滚现实动作。CI 固定使用 Mock，不访问网络模型。普通解析和动作选择使用 non-thinking；复杂重规划才考虑 thinking，且不得保存或展示推理内容。

本地 Ollama 请求直连 loopback，不继承系统代理；解析使用 JSON Schema 输出并保持本地 Pydantic 校验。若模型漏掉输入中唯一明确的 `N分钟后`，适配层只补回该数字并再次验证 schema；含糊或多个时间仍需用户澄清。此校正不赋予模型或适配层修改业务状态的权限。
