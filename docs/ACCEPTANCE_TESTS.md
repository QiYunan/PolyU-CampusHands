# CampusHands 验收场景

以下 Given/When/Then 是阶段完成的可观察证据。阶段范围以对应 [里程碑](milestones/01-mvp-foundation.md)为准；目标用户体验见 [产品规格](PRODUCT_SPEC.md)，状态规则见 [Agent 工作流](AGENT_WORKFLOW.md)。场景使用可重建的虚构数据和离线测试环境。

## 01 基础闭环

**AT-01 创建并持久化。** Given 空的演示数据库与 Alice 的 Requester 页面，When Alice 用结构化表单提交科学计算器、VA 和未来截止时间，Then 前端显示服务端返回的请求 ID 与 `draft` 状态；`GET /api/requests/{id}` 返回相同字段；刷新页面及重启后端后仍能读取该记录。

**AT-02 输入边界。** Given 创建表单，When 必需字段为空或截止时间已经过去，Then API 返回可识别的验证错误，前端显示对应提示，数据库不新增请求。

**AT-03 第一阶段隔离。** Given 仅安装并启动第一阶段组件，When 执行 AT-01 与健康检查，Then 流程无需模型 key、DeepSeek、Ollama、MockLLM、Helper Inbox 或 WebSocket；没有对真实 LLM 的网络调用。

## 02 BorrowLoop 确定性流程

**AT-04 开放广场与排序。** Given 多名 Helper 的预设库存、位置、availability 和信誉各不相同，When Alice 发布物品或服务请求，Then 所有人都看到同一开放请求且“我可以帮助”可点击。广场只按紧急程度、截止时间、发布时间和稳定 ID 排序；任何预设 Helper 字段都不控制资格或显示内部原因。

**AT-05 自主参与与隐藏。** Given Alice 的请求已发布到广场，When Bob 选择“暂不参与”，Then 该请求只从 Bob 的广场隐藏，Carol 和其他 Helper 继续看到，Alice 的时间线无该动作；Bob 恢复后重新看到同一请求。重复隐藏或恢复保持幂等，没有 `pending` Offer。

**AT-06 响应与完成。** Given Erin 和 Grace 同时看到开放请求，When 一人在弹窗确认能按时完成并提交响应，Then 服务创建唯一 `accepted` Offer（可无 `item_id`）、请求进入 `matched` 并显示安全帮助说明；When Alice 与获胜 Helper 分别确认完成，Then 请求才进入 `completed`。任一方单独确认不足以完成。

**AT-07 截止与幂等。** Given 已发布但无人认领的请求，When 重复运行截止检查，Then 截止前请求保持 `awaiting_response`，没有任何个人 30 秒邀请超时；截止时间到达后恰好进入一次 `expired`，不再接受认领或发布。重复发布只写一次公开发布事件。

**AT-08 非法操作。** Given 已完成、已取消或已由他人认领的请求，When 再次认领、取消或完成，Then 服务层拒绝非法转换且数据库状态不变；其他演示角色不能确认不属于自己的交接。

**AT-08a 匹配后的截止与空物品关联。** Given Carol 已响应服务请求或自主声明物品响应，Offer 的 `item_id` 为空，When 请求截止、Requester 取消或双方完成，Then `matched`／`in_progress` 不自动过期，取消和双确认均不报错，也不尝试解引用不存在的预设物品。

## 03 Agent 与模型

**AT-09 通用解析与澄清。** Given 固定时钟，When Mock 分别解析已知借物、任意物品与“20分钟后，在Z栋，需要同学帮我搬运实验器材，有偿”，Then 得到 `borrow`／`service`、用户可核对的 `need_summary`、未知项 `other`、地点和截止时间，服务请求不出现科学计算器；When 摘要、地点或截止时间缺失，Then 只提出所缺字段，不要求服务补物品类型。

**AT-09a 原子草稿确认。** Given 已解析借物草稿，When 用户在当前页面输入 `Casio`、`fx-991cnx`、`exact_only`、高紧急程度并直接点击“确认并创建请求”，Then confirm 请求一次发送当前全部字段，后端在同一事务中应用并创建正式 `draft`，任何字段不丢失；无需先 PATCH“保存修改”。重复确认只返回同一正式请求。

**AT-10 Provider fallback。** Given 主 provider 超时或返回 429/5xx，When 一次安全重试仍失败，Then 尝试 Ollama；Given 两者均失败，Then 返回可恢复错误且没有虚构匹配、重复 Offer 或状态跃迁。

**AT-10a 动作边界。** Given 模型提议未知工具、非法参数、与当前请求不符的 ID，或试图指定 Helper／Item ID，When Orchestrator 校验，Then 不执行业务动作；Given 发布已提交后模型失败，Then 返回真实请求 ID 和权威状态，重试不重复发布；`finish` 与 `wait_for_response` 不更改借物状态，后者立即结束请求。模型只可提出经白名单与 Schema 验证的 `publish_request` 等高层动作。

**AT-11 隐私与离线 CI。** Given 测试与演示配置，When 运行后端和前端测试或读取公开 API/时间线，Then 测试不调用真实模型，响应与日志不出现 API key、学生证号、电话或隐藏推理。

**AT-11a 状态与默认界面。** Given DeepSeek 未配置或本地 Ollama 不可用，When 读取 System Status 或提交自然语言请求，Then页面显示可恢复错误，但默认不建议或展示绕过 Agent 的结构化调试表单；只有显式 `VITE_SHOW_STRUCTURED_DEBUG_FORM=true` 的开发环境可恢复该入口。状态接口不触发付费探测或返回密钥。

## 04 实时更新

**AT-12 广场推送。** Given Alice 查看请求、Erin 和 Grace 各自打开广场，When Alice 发布，Then两位 Helper 均无需手动刷新即可看到同一请求；When 其中一人认领，Then Alice 看见 `matched`，所有 Helper 广场实时关闭该请求。Given WebSocket 断线或通知重复，When 客户端重连或两秒轮询，Then 通过 HTTP GET 对齐权威状态和持久化事件。广场 WebSocket 仅发送变化通知；无权角色不能订阅，通知失败不回滚事务，也不泄露库存、位置、候选数、评分或隐藏推理。

## 05 演示与协作

**AT-13 三设备课堂演示。** Given 专用 Demo reset 后的 Alice、Erin、Grace 虚构数据及显式 Mock Recovery Mode，When 三名组员在同一 LAN 的不同设备登录各自 Demo 角色，Alice 输入 Z 栋 Casio 请求并启动 Agent `publish_request`，Then Erin 和 Grace 同时无需刷新看到请求；两人在确认弹窗勾选能力后几乎同时响应，恰好一人成功、另一人收到安全 409，广场实时关闭，Alice 与获胜 Helper 完成双确认。再用搬运器材服务请求验证无预设物品也可完成。全程不等待个人 Offer 超时、不依赖固定认领顺序或真实学生。

**AT-14 工程检查。** Given 干净的检出与文档化的启动步骤，When 安装依赖、对固定 Demo 数据库重复 reset、运行 setup/ready preflight，并在 CI 执行后端全量 pytest、前端 test/lint/build 和跟踪文件检查，Then 均能给出可靠退出码、CI 不访问真实 DeepSeek/Ollama，开发数据库及 `.env` 不被 reset 触碰；提交内容不含真实 key、数据库、日志、模型文件或真实用户数据。故障恢复、刷新、后端重启、双 provider 失败与 WebSocket 轮询回退按 [演示手册](DEMO_RUNBOOK.md)复核。

## 06 Matching Quality & Campus Coverage

**AT-15 自主响应与地点。** Given G 栋或 Z 栋请求及没有预设物品、位置未知或 availability 非 available 的 Helper，When 请求发布，Then 所有 Helper 都看到且按钮可点击；只要在弹窗确认能力，服务不因这些预设字段拒绝。Requester 地点别名仍标准化，未知地点在正式创建前澄清。

**AT-16 品牌与替代提案。** Given `exact_only` 请求，When Helper 填写不匹配品牌／型号，Then 不能直接认领；规范化后的准确值可认领。Given `ask_before_substitute` 且填写不同品牌／型号，Then 创建 `proposed` Offer，请求保持开放；只有 Alice 可接受或拒绝。接受前不匹配，接受后产生唯一 accepted Offer 并取消其他提案。`equivalent_ok` 的已确认替代响应可直接认领。

**AT-17 服务闭环与并发。** Given 搬运实验器材服务请求，When发布、Helper 能力确认、开始交接和双方确认，Then 全程不要求预设物品，Offer 的 `item_id` 可为空且最终完成。Given 两名 Helper 并发直接响应同一请求，Then `BEGIN IMMEDIATE` 与唯一索引保证恰好一人成功，另一人收到安全 409。

**AT-18 摘要、紧急程度与界面。** Given item、任意物品和 service 三种 Mock 输入，When解析、确认、发布和查看详情／广场，Then `category`、`need_summary`、`other` 兜底及 `urgency` 正确持久化并显示；标题不默认显示科学计算器。默认页面没有结构化调试入口，显式开发开关可恢复；Helper 页面不显示预设库存、当前位置或内部资格原因。

**AT-19 旧库迁移。** Given `help_offers.item_id NOT NULL` 且含请求、草稿、Offer、事件的旧 SQLite 副本，When 初始化两次，Then `need_summary` 回填、新响应字段存在、`item_id` 变为可空，旧原文、状态、事件、Offer、唯一约束及数据不丢失；旧终态不被复活，隔离 Demo reset 不触碰开发数据库。

**AT-20 Agent、隐私与实时。** Given Mock 模型提出合法或非法动作，When执行，Then schema 允许物品、任意物品和服务，非法工具／参数仍被拒绝；模型不能提供 Helper／Item ID 或执行任意代码。Requester API 只显示已提交提案的安全字段；广场、时间线和 WebSocket 不泄露预设库存、Helper 位置、availability、信誉或隐藏推理。WebSocket 失败时两秒轮询仍用 GET 对齐。

**AT-21 离线回归与浏览器验收。** Given 固定 Mock 配置与隔离 Demo 数据库，When执行后端全量 pytest、前端 test/lint/build、`git diff --check`、跟踪文件检查和浏览器闭环，Then Milestone 01–05 仍适用场景通过，物品／服务、原子确认、提案、并发、取消、完成和刷新流程完成，自动化不读取 `backend/.env`、不访问 DeepSeek 或 Ollama。最终三台物理设备验收另行如实记录，单机多上下文不等同于完成该项。

**AT-22 临时公网拍摄。** Given Mock、隔离 Demo 数据库、显式规范 `CAMPUSHANDS_PUBLIC_DEMO_ORIGINS`、与其逐项对应的 `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS`，以及只指向 loopback Vite 5173 的 Quick Tunnel，When Alice 与 Helper 从不同网络打开同一随机 HTTPS URL，Then 首页和同源 `/api` 可用，Requester 与 Helper-board 通过保留原始 HTTPS Origin 的 WSS 完成权限校验、失效通知和 GET 对齐；未获准 Origin、错误角色或资源仍以 1008 拒绝。断开 WebSocket 后两秒轮询继续同步。停止 cloudflared 后该 URL 不可访问，本机与热点 LAN 模式不变；全程不公开 8000、11434、SQLite，不调用真实 Provider，不使用真实身份或资料。
