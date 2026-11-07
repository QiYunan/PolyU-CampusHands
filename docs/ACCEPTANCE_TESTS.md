# CampusHands 验收场景

以下 Given/When/Then 是阶段完成的可观察证据。阶段范围以对应 [里程碑](milestones/01-mvp-foundation.md)为准；目标用户体验见 [产品规格](PRODUCT_SPEC.md)，状态规则见 [Agent 工作流](AGENT_WORKFLOW.md)。场景使用可重建的虚构数据和离线测试环境。

## 01 基础闭环

**AT-01 创建并持久化。** Given 空的演示数据库与 Alice 的 Requester 页面，When Alice 用结构化表单提交科学计算器、VA 和未来截止时间，Then 前端显示服务端返回的请求 ID 与 `draft` 状态；`GET /api/requests/{id}` 返回相同字段；刷新页面及重启后端后仍能读取该记录。

**AT-02 输入边界。** Given 创建表单，When 必需字段为空或截止时间已经过去，Then API 返回可识别的验证错误，前端显示对应提示，数据库不新增请求。

**AT-03 第一阶段隔离。** Given 仅安装并启动第一阶段组件，When 执行 AT-01 与健康检查，Then 流程无需模型 key、DeepSeek、Ollama、MockLLM、Helper Inbox 或 WebSocket；没有对真实 LLM 的网络调用。

## 02 BorrowLoop 确定性流程

**AT-04 候选过滤。** Given Bob 位于 VA 且有可借科学计算器、Carol 位于 PQ 且有可借科学计算器、David 只有 USB-C 充电器，且预设 VA 比 PQ 更适合在截止前交接，When 为 VA 的科学计算器请求搜索并排序，Then Bob 排在 Carol 前，David 被排除；不可用或截止前无法交接的帮助者也被排除。

**AT-05 拒绝后重试。** Given Alice 的请求已向 Bob 发出一条待答 Offer，When Bob 拒绝，Then Bob 的 Offer 变为 `declined`，请求回到 `searching` 后向 Carol 发出一条待答 Offer 并回到 `awaiting_response`；Bob 不再收到同一轮重复邀请。

**AT-06 接受与完成。** Given Carol 收到待答 Offer，When Carol 接受，Then 请求进入 `matched` 并显示交接信息；When 双方开始交接且 Alice 与 Carol 分别确认完成，Then 请求才进入 `completed`。任一方单独确认不足以完成。

**AT-07 超时与幂等。** Given Bob 的 Offer 超过 `expires_at` 且 Carol 尚未联系，When 超时检查重复执行两次，Then Bob 只留下一个 `expired` Offer 和一条公开超时事件，Carol 最多收到一条 Offer；请求截止时间到达时不再联系候选人，请求进入 `expired`。

**AT-08 非法操作。** Given 已完成或已取消的请求，When 再次接受、取消或完成，Then 服务层拒绝非法转换且数据库状态不变；其他演示角色不能操作不属于自己的 Offer。

**AT-08a 匹配后的截止与预留。** Given Carol 已接受且物品被预留，When 请求截止时间到达，Then `matched` 或 `in_progress` 请求不自动过期；When Requester 取消，Then 预留物品重新可用；When 双方完成确认，Then 物品保持不可用。

## 03 Agent 与模型

**AT-09 解析与澄清。** Given 固定时钟及中文借物输入“我 20 分钟后在 VA 考试，但计算器坏了，想借一部科学计算器”，When Mock provider 解析，Then 得到 `borrow`、`scientific_calculator`、`VA` 和相对固定时钟计算的截止时间；When 地点或截止时间缺失，Then 只提出所缺字段的澄清问题，不向帮助者发送 Offer。

**AT-09a 草稿确认。** Given 自然语言请求缺地点和时限，When 用户补充字段、修改解析结果并刷新页面，Then 同一 `HelpRequestDraft` 仍可读取已确认的公开字段；When 用户确认两次，Then 只创建一条正式 `draft` 请求并返回同一 ID；确认前数据库无对应正式请求和 Offer。

**AT-10 Provider fallback。** Given 主 provider 超时或返回 429/5xx，When 一次安全重试仍失败，Then 尝试 Ollama；Given 两者均失败，Then 返回可恢复错误且没有虚构匹配、重复 Offer 或状态跃迁。

**AT-10a 动作边界。** Given 模型提议未知工具、非法参数或与当前请求不符的 ID，When Orchestrator 校验，Then 不执行业务动作；Given Offer 已提交后模型失败，Then 返回真实请求 ID 和权威状态，重试不会产生第二条 Offer；`finish` 与 `wait_for_response` 不更改借物状态，后者立即结束请求；拒绝后 Agent 观察结果不额外发送 Offer。

**AT-11 隐私与离线 CI。** Given 测试与演示配置，When 运行后端和前端测试或读取公开 API/时间线，Then 测试不调用真实模型，响应与日志不出现 API key、学生证号、电话或隐藏推理。

**AT-11a 状态与保密。** Given DeepSeek 未配置或本地 Ollama 不可用，When 读取 System Status 或提交自然语言请求，Then 页面仍可使用结构化表单；状态接口只显示 provider 类别、可用状态和 fallback 状态，不触发付费探测或返回密钥。

## 04 实时更新

**AT-12 状态推送。** Given Alice 正在查看请求、Bob 和 Carol 打开各自 Inbox，When Bob 拒绝，Then Alice 无需手动刷新即可看到按 ID 排序的公开事件，Carol 无需手动刷新即可看到新 Offer；When Carol 接受，Then Alice 无需手动刷新即可看到 `matched`。Given WebSocket 断线或通知重复，When 客户端重连或两秒轮询，Then 通过 HTTP GET 对齐权威状态和持久化事件，时间线不重复。无权角色不能订阅；通知失败不回滚已提交事务，通知中不含密钥或隐藏推理。

## 05 演示与协作

**AT-13 五分钟演示。** Given 专用 Demo reset 后的 Alice/Bob/Carol/David 数据、Demo Mode，以及计时前选定并明确标识的真实 provider 或 Mock Recovery Mode，When Alice 用自然语言提出限时借计算器请求、确认解析字段并启动 Agent，Bob 拒绝、Carol 接受、双方确认交接，Then 在不超过 4 分 30 秒（含至少 30 秒缓冲）内看到本地验证后交给服务的工具名称、每一步服务端状态、实时更新和公开时间线；不依赖真实学生或外部通知，不把 Mock 称为真实模型。

**AT-14 工程检查。** Given 干净的检出与文档化的启动步骤，When 安装依赖、对固定 Demo 数据库重复 reset、运行 setup/ready preflight，并在 CI 执行后端全量 pytest、前端 test/lint/build 和跟踪文件检查，Then 均能给出可靠退出码、CI 不访问真实 DeepSeek/Ollama，开发数据库及 `.env` 不被 reset 触碰；提交内容不含真实 key、数据库、日志、模型文件或真实用户数据。故障恢复、刷新、后端重启、双 provider 失败与 WebSocket 轮询回退按 [演示手册](DEMO_RUNBOOK.md)复核。
