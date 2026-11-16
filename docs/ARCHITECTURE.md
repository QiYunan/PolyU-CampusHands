# CampusHands 架构

## 组件与连接

目标是单仓库的 `frontend/`、`backend/`、`docs/` 与 `.github/workflows/`。前端采用 React、TypeScript、Vite、React Router、轻量 CSS、Vitest 和 `fetch` 或薄 API client；后端采用 Python 3.11+、FastAPI、Pydantic、SQLAlchemy、SQLite 和 pytest。第四阶段用 WebSocket 推送实时状态；第三阶段才引入统一 LLM provider 接口及兼容接口所需的 Python SDK。第一阶段不引入任何真实 LLM 依赖或调用。

```text
本机／LAN 浏览器 ──HTTP/WS──> Vite 5173 ──/api、/ws 代理──> FastAPI 8000
公网拍摄浏览器 ──HTTPS/WSS──> Cloudflare ──cloudflared──┘
                                                        │
                                                        ▼
                                               服务层 / 状态机 / 权限
                                                  │            │
                                                  ▼            ▼
                                             SQLAlchemy      Agent 编排
                                                  │            │
                                                  ▼            ▼
                                                SQLite      Provider 接口
```

浏览器使用相对 `/api` 与 `/ws` 连接 Vite，由 Vite 代理到 FastAPI；FastAPI 仍是唯一业务 API。路由负责 HTTP 与 schema 边界；服务层负责事务、能力确认、品牌规则、替代提案、广场排序、原子认领、状态转换、截止时间、权限和幂等；Agent 只能通过经验证的服务工具提出发布动作。预设库存、Helper 位置、availability、步行时间和信誉不参与新响应资格。详细动作顺序见 [Agent 工作流](AGENT_WORKFLOW.md)。第一阶段只建足以完成持久化闭环的组件；无需 Kubernetes、微服务、Redis、Celery、复杂队列、付费地图或云基础设施。

## 数据与一致性

目标实体如下。字段是逻辑契约，具体类型、索引和迁移在实施时定稿。

| 实体 | 字段 | 约束与用途 |
| --- | --- | --- |
| `User` | `id`, `display_name`, `campus_building`, `availability_status`, `reliability_score`, `created_at` | 演示身份；`reliability_score` 不决定认领归属，也不公开。 |
| `UserItem` | `id`, `user_id`, `item_type`, `item_name`, 可空 `brand`, `model`, `available` | 历史库存与演示兼容数据；不再控制新流程响应资格。 |
| `HelpRequest` | `id`, `requester_id`, `category`, `raw_text`, `need_summary`, `item_type`, `preferred_brand`, `preferred_model`, `substitution_policy`, `matching_issue`, `location`, `deadline`, `urgency`, `status`, `created_at`, `updated_at` | 物品／服务请求、用户确认摘要、借物偏好、时限和权威状态；服务与未知物品用 `other`。 |
| `HelpOffer` | `id`, `request_id`, `helper_id`, 可空 `item_id`, `response_type`, `help_note`, `offered_brand`, `offered_model`, `capability_confirmed_at`, `status`, 时间字段及双方确认时间 | 自主响应记录；`accepted` 表示唯一匹配，`proposed` 等待 Requester 接受。服务或自主声明无需预设物品。 |
| `RequestDismissal` | `request_id`, `helper_id`, `created_at` | 当前 Helper 隐藏一条开放请求；组合唯一，恢复时删除，不进入 Requester 时间线。 |
| `AgentEvent` | `id`, `request_id`, `event_type`, `public_message`, `metadata_json`, `dedupe_key`, `created_at` | 可公开且可去重的操作事件；不保存隐藏推理。 |
| `HelpRequestDraft` | `id`, `requester_id`, `raw_text`, `category`, 可空 `need_summary` 与其他解析字段、公开澄清内容、`status`, `request_id`, UTC 时间 | 自然语言不完整输入；当前完整表单被原子确认前不创建正式请求或 Offer。 |

第一阶段至少持久化演示 `User` 与 `HelpRequest`；其余实体在对应里程碑增加。时间戳与截止时间以 UTC 存储，在界面按本地时间显示。草稿确认、发布、直接认领、提案接受和事件写入在一致的数据库事务内完成；认领以 SQLite `BEGIN IMMEDIATE` 串行化，并由每个请求最多一条 accepted Offer 的唯一索引兜底。重复命令不得产生第二条成功认领。`metadata_json` 只存非敏感的结构化操作信息。

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
| 04 | `WS /ws/requests/{request_id}`, `WS /ws/helpers/{helper_id}/offers` | 推送请求公开事件与 Helper 自己的 Inbox 变化通知。 |
| 06 | `GET /api/locations`, `GET /api/demo/roles`, `PATCH /api/requests/{id}`, `POST /api/requests/{id}/publish` | 地点与虚构角色选项；Requester 更正并发布。旧 `/search` 保留为发布语义兼容入口。 |
| 06 | `GET /api/helper-board`, `POST /api/requests/{id}/claim`, `/dismiss`, `/restore`, `WS /ws/helper-board?demo_user_id={id}` | 所有 Helper 读取同一开放广场；claim 提交能力确认、说明及可选实际品牌／型号；WebSocket 仅通知变化。 |
| 06 | `POST /api/offers/{id}/accept-proposal`, `POST /api/offers/{id}/decline-proposal` | 仅 Requester 接受或拒绝具体替代提案；接受时原子产生唯一匹配。 |
| 07 | `GET/PUT /api/demo/users/{id}/helper-profile`, `GET/PUT /api/demo/users/{id}/daily-availability` | Helper 私有的长期供给资料和香港本地“今日状态”。 |
| 07 | `POST /api/helpers/search`, `POST/GET /api/requests/{id}/invitations`, `POST /api/requests/{id}/invitations/close` | AI 与手动页面共用确定性搜索；Requester 创建、查看和结束邀请轮次。 |
| 07 | `GET /api/helpers/{id}/invitations`, `POST /api/invitations/{id}/accept|decline|propose-substitute` | Helper 私有邀请收件箱及受控响应。 |
| 07 | `WS /ws/helpers/{id}/invitations` | 邀请变化失效通知；GET 快照和两秒轮询保持权威。 |

`/start` 在已匹配后记录开始交接；`/complete` 记录 Requester 的确认；只有对应 Helper 也确认后，服务层才可进入 `completed`。原始清单缺少开始交接与 Helper 确认接口，因此在此补充。第一阶段请求输入为结构化字段；第三阶段增加自然语言解析入口时保持服务层的请求创建规则一致。具体输入输出 schema 在实现该阶段时确定。

第二阶段的本地 Demo Mode 用 `X-Demo-User-Id` 表示当前虚构角色。原有请求接口缺少该 header 时默认为 Alice；Helper 广场和认领操作必须带当前 Helper ID，服务层核验角色。该 header 可由本地用户切换，不是生产级认证。前端在 WebSocket 断开时每两秒用 HTTP 读取权威状态；单进程定时检查只使尚未认领的开放请求在截止时间到达时过期，新流程没有个人 30 秒邀请超时。

第四阶段的 WebSocket 只传输通知。浏览器以 `demo_user_id` 查询参数表示虚构角色，握手前由服务核对请求或 Helper 广场权限；本地 Origin 固定，课堂 LAN Origin 由 `CAMPUSHANDS_LAN_ORIGINS` 显式列出 RFC1918 `http://IP:5173`，临时公网拍摄 Origin 由独立的 `CAMPUSHANDS_PUBLIC_DEMO_ORIGINS` 显式列出规范 `https://<subdomain>.trycloudflare.com`。两类配置都拒绝通配符，公网配置不会放宽 LAN 规则。这不构成生产认证。独立扫描器每 250 毫秒按 `AgentEvent.id` 升序读取已提交事件，使用该 ID 作为全局游标；只有读取、验证和路由成功后才前移游标。单个连接的队列或发送失败只移除该连接，不影响事务和其他订阅者。发布、认领、取消和过期向所有已连接 Helper 发送不含候选信息的广场变化通知。前端先 GET、订阅后再 GET，后续收到通知时重读 HTTP 权威快照；断线后继续两秒轮询。内存连接管理仅适用于单进程 Demo，不支持多实例消息传播。

Quick Tunnel 模式只把 `http://127.0.0.1:5173` 交给本机 `cloudflared`；FastAPI 和 Vite 都继续监听 loopback。Vite 只允许 `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS` 中逐个列出的具体 TryCloudflare hostname，并在 `/ws` 代理中保留浏览器的 HTTPS Origin，供 FastAPI 执行相同权限检查。该模式不新增 CORS，不直接暴露 8000、11434、SQLite 或其他端口，也不是生产部署。课堂正式 Live Demo 继续使用自有热点 LAN。

第三阶段的 Agent 草稿独立于正式 `HelpRequest`。确认接口接收页面当前完整字段，并在同一事务中应用编辑、验证和创建正式 `draft`；重复确认返回相同 ID。旧 SQLite 除幂等加列外，还在事务中重建 legacy Offer 表，使 `item_id` 可空并保留数据与唯一索引。模型仅收到可公开的最少结构化观察；DeepSeek 与 Ollama 使用相同的受限工具 schema，并由本地 Pydantic 再次验证。`finish` 只结束一次 Agent loop，`wait_for_response` 立即返回当前状态；两者都不改变业务状态。

第五阶段在 `AgentRunRead` 中增加 `validated_actions`：仅列出经本地 schema 校验且已交给确定性服务执行的受控工具名称，不包含参数、原始模型响应或推理。`/api/system/llm-status` 的 `active` 只代表本次成功的模型调用；尚未调用或本次双 provider 失败时为 `null`。`unknown` 表示尚未调用，不能当作可用性证明。Demo reset 固定作用于 `backend/.demo/campushands.db`，与默认开发数据库隔离；Demo 后端在运行时持有进程锁，reset 遇到占用即拒绝。操作与两阶段 preflight 见 [演示手册](DEMO_RUNBOOK.md)。

第六阶段继续使用版本化离线地点 registry 与别名，只标准化 Requester 的交接地点。旧步行图与估算分钟可为历史数据兼容保留，但不参与新广场显示、排序或认领资格，也不是导航。地点依据 [PolyU Campus Map](https://www.polyu.edu.hk/cdo/docdrive/Useful%20Information/CampusMap.pdf) 与 [Campus Access](https://www.polyu.edu.hk/cfso/informationhub/access-to-campus-and-premises/)；项目不声称实时通行保证。广场 API 不返回预设库存、Helper 地点、availability、步行分钟或信誉；Requester 事件也不保存这些内部数据。

第七阶段新增 `UserServiceCapability`、`DailyAvailability` 及其今日物品／服务关联、`InvitationBatch` 和 `HelpInvitation`。定向邀请与旧 `HelpOffer` 分离；只有成功接受后才创建 accepted Offer，因此多轮邀请历史不会破坏 M06 的 Offer 兼容约束。搜索先应用今日状态、能力、可达性、紧急偏好、活动任务和拒绝历史等硬条件，再做稳定词典序排序。Requester 只看到请求相关理由、预计到达和等级化信誉；Helper 的楼栋、完整库存和原始分数不跨越 API 或 WebSocket。旧公开广场只识别 `request_published` 事件，M07 `invitations_sent` 不会使定向请求进入该广场。

## 安全边界

- 演示角色切换只代表本地 Demo Mode 的模拟身份，不构成真实 PolyU 认证或生产级权限证明。服务层仍按当前演示角色检查记录归属；真实部署前必须另行设计认证。
- DeepSeek API key 仅从被忽略的 `backend/.env` 文件读取；其他 provider 设置可由后端环境变量或该文件提供。`.env`、SQLite 文件、上传、日志、`node_modules` 和虚拟环境不提交。示例配置不得含真实密钥。前端和公开状态接口不得暴露密钥。
- 向云模型只发送完成任务所需的最少数据，尽量使用匿名 ID；不发送学生证号、电话或无关个人资料。对日志中的密钥和敏感内容做遮蔽。
- 对模型返回和所有 tool arguments 做 Pydantic/schema 校验；模型不得直接执行任意代码或 SQL，不得生成伪造的数据库事实。
- Ollama 仅由后端访问，不把其服务端口直接暴露给局域网。离线 CI 不调用真实 DeepSeek 或 Ollama。
- Quick Tunnel URL 的持有者可访问临时 Demo；公网拍摄只使用 Mock、虚构身份和虚构数据，结束后立即停止 Tunnel。Vite 开发服务器内容可能在这段时间被 URL 持有者读取，因此不得把真实资料、密钥或私有文件放入前端可服务范围。

产品范围见 [产品规格](PRODUCT_SPEC.md)，状态机和 provider 失败处理见 [Agent 工作流](AGENT_WORKFLOW.md)。
