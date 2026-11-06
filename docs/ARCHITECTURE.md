# CampusHands 架构

## 组件与连接

目标是单仓库的 `frontend/`、`backend/`、`docs/` 与 `.github/workflows/`。前端采用 React、TypeScript、Vite、React Router、轻量 CSS、Vitest 和 `fetch` 或薄 API client；后端采用 Python 3.11+、FastAPI、Pydantic、SQLAlchemy、SQLite 和 pytest。第四阶段用 WebSocket 推送实时状态；第三阶段才引入统一 LLM provider 接口及兼容接口所需的 Python SDK。第一阶段不引入任何真实 LLM 依赖或调用。

```text
浏览器 UI ──HTTP（第四阶段另有 WebSocket）──> FastAPI 路由
                                              │
                                              ▼
                                     服务层 / 状态机 / 权限
                                        │            │
                                        ▼            ▼
                                   SQLAlchemy      Agent 编排（第三阶段）
                                        │            │
                                        ▼            ▼
                                      SQLite      Provider 接口
```

前端只连接 FastAPI。路由负责 HTTP 与 schema 边界；服务层负责事务、过滤排序、状态转换、超时、权限和幂等；Agent 只能通过经验证的服务工具提出动作。详细动作顺序见 [Agent 工作流](AGENT_WORKFLOW.md)。第一阶段只建足以完成持久化闭环的组件；无需 Kubernetes、微服务、Redis、Celery、复杂队列、付费地图或云基础设施。

## 数据与一致性

目标实体如下。字段是逻辑契约，具体类型、索引和迁移在实施时定稿。

| 实体 | 字段 | 约束与用途 |
| --- | --- | --- |
| `User` | `id`, `display_name`, `campus_building`, `availability_status`, `reliability_score`, `created_at` | 演示身份；`reliability_score` 仅内部使用，不公开排名。 |
| `UserItem` | `id`, `user_id`, `item_type`, `item_name`, `available` | 帮助者拥有且可借出的物品。 |
| `HelpRequest` | `id`, `requester_id`, `category`, `raw_text`, `item_type`, `location`, `deadline`, `urgency`, `status`, `created_at`, `updated_at` | 请求、时限和权威状态；第一阶段允许从结构化表单填充。 |
| `HelpOffer` | `id`, `request_id`, `helper_id`, `item_id`, `status`, `sent_at`, `responded_at`, `expires_at`, 双方确认时间 | 一次站内邀请、回复或超时及交接确认；同一请求与 Helper 最多一条。 |
| `AgentEvent` | `id`, `request_id`, `event_type`, `public_message`, `metadata_json`, `dedupe_key`, `created_at` | 可公开且可去重的操作事件；不保存隐藏推理。 |
| `HelpRequestDraft` | `id`, `requester_id`, `raw_text`, 可空解析字段、公开澄清内容、`status`, `request_id`, UTC 时间 | 第三阶段的不完整输入；字段确认前不创建正式请求或 Offer。 |

第一阶段至少持久化演示 `User` 与 `HelpRequest`；其余实体在对应里程碑增加。时间戳与截止时间以 UTC 存储，在界面按本地时间显示。修改请求、Offer 和事件的服务操作应在一致的数据库事务内完成；重复命令不得产生重复 Offer 或重复终态。`metadata_json` 只存非敏感的结构化操作信息。

## API 边界与交付阶段

下表是计划中的 HTTP 契约；除第一阶段列出的接口外，均属后续阶段。FastAPI 提供 OpenAPI 文档。

| 阶段 | 接口 | 用途 |
| --- | --- | --- |
| 01 | `POST /api/requests`, `GET /api/requests/{id}`, `GET /api/system/health` | 创建并重新读取持久化请求；健康检查。 |
| 02 | `POST /api/requests/{id}/search`, `POST /api/requests/{id}/cancel`, `POST /api/requests/{id}/start`, `POST /api/requests/{id}/complete` | 从草稿开始匹配、取消、开始交接、Requester 确认交接完成。 |
| 02 | `GET /api/helpers/{id}/offers`, `POST /api/offers/{id}/accept`, `POST /api/offers/{id}/decline`, `POST /api/offers/{id}/confirm-completion` | Helper 站内邀请、应答及交接确认。 |
| 03 | `GET /api/system/llm-status` | 返回当前 provider 类别和可用状态，不返回密钥。 |
| 03 | `POST /api/agent/drafts`, `GET/PATCH /api/agent/drafts/{id}`, `POST /api/agent/drafts/{id}/clarify`, `POST /api/agent/drafts/{id}/confirm` | 解析、澄清、修改及幂等确认自然语言草稿。 |
| 03 | `POST /api/agent/requests/{id}/search`, `POST /api/agent/requests/{id}/observe` | 模型提出受控动作或观察进展；现有服务决定匹配与邀请。 |
| 04 | `WS /ws/requests/{request_id}` | 推送请求状态及公开事件。 |

`/start` 在已匹配后记录开始交接；`/complete` 记录 Requester 的确认；只有对应 Helper 也确认后，服务层才可进入 `completed`。原始清单缺少开始交接与 Helper 确认接口，因此在此补充。第一阶段请求输入为结构化字段；第三阶段增加自然语言解析入口时保持服务层的请求创建规则一致。具体输入输出 schema 在实现该阶段时确定。

第二阶段的本地 Demo Mode 用 `X-Demo-User-Id` 表示当前虚构角色。原有请求接口缺少该 header 时默认为 Alice；Helper Inbox 和 Offer 操作必须带当前 Helper ID，服务层检查归属。该 header 可由本地用户切换，不是生产级认证。前端每两秒用 HTTP 读取公开状态；服务端以单进程定时检查处理 Offer 超时，并在重启后补处理到期记录。WebSocket 留待第四阶段。

第三阶段的 Agent 草稿独立于字段均非空的正式 `HelpRequest`。确认草稿在同一事务中创建正式 `draft` 请求，重复确认返回相同 ID。`HelpOffer.message` 是可空的公开邀请文案，旧 SQLite 数据库以幂等加列方式升级。模型仅收到可公开的最少结构化观察；DeepSeek 与 Ollama 使用相同的受限工具 schema，并由本地 Pydantic 再次验证。`finish` 只结束一次 Agent loop，`wait_for_response` 立即返回当前状态；两者都不改变业务状态。

## 安全边界

- 演示角色切换只代表本地 Demo Mode 的模拟身份，不构成真实 PolyU 认证或生产级权限证明。服务层仍按当前演示角色检查记录归属；真实部署前必须另行设计认证。
- DeepSeek API key 仅从被忽略的 `backend/.env` 文件读取；其他 provider 设置可由后端环境变量或该文件提供。`.env`、SQLite 文件、上传、日志、`node_modules` 和虚拟环境不提交。示例配置不得含真实密钥。前端和公开状态接口不得暴露密钥。
- 向云模型只发送完成任务所需的最少数据，尽量使用匿名 ID；不发送学生证号、电话或无关个人资料。对日志中的密钥和敏感内容做遮蔽。
- 对模型返回和所有 tool arguments 做 Pydantic/schema 校验；模型不得直接执行任意代码或 SQL，不得生成伪造的数据库事实。
- Ollama 仅由后端访问，不把其服务端口直接暴露给局域网。离线 CI 不调用真实 DeepSeek 或 Ollama。

产品范围见 [产品规格](PRODUCT_SPEC.md)，状态机和 provider 失败处理见 [Agent 工作流](AGENT_WORKFLOW.md)。
