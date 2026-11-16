# 06 · Open Campus Help Board

## 目标

支持物品和服务两类校园求助。所有 Helper 看到开放请求后自行判断能力，通过确认弹窗响应；预设库存、预设位置、available 状态、步行时间和信誉不再决定按钮是否可用。模型只能解析请求并提出受控的高层发布动作，不能选择 Helper、确认现实能力或决定匹配结果。

## 交付范围

- `HelpRequest` 保存 `category`、用户确认的 `need_summary`、内部 `item_type`（未知物品和服务使用 `other`）、地点、截止时间及紧急程度。品牌、型号和替代规则只对 `borrow` 生效。旧请求按原 `item_type` 幂等回填摘要。
- Agent schema 和 Mock／兼容 provider 同时支持物品、任意物品和服务。必填字段是需求摘要、地点和截止时间；“20分钟后，在Z栋，需要同学帮我搬运实验器材，有偿”解析为 `service`，不得出现科学计算器或要求补充物品类型。
- 自然语言草稿只保留一个“确认并创建请求”动作。前端把当前完整表单随确认发送；后端在同一事务中应用编辑、重新校验并创建正式请求，不能确认旧的服务器草稿。默认界面隐藏结构化 Demo／调试表单；仅显式 `VITE_SHOW_STRUCTURED_DEBUG_FORM=true` 可恢复。
- 离线地点 registry 只校验和标准化 Requester 的交接地点，不评估某位 Helper 能否到达。广场向所有 Helper 显示全部开放请求，按紧急程度、截止时间、发布时间和稳定 ID 排序，不展示预设库存、当前位置、availability 或内部资格原因。
- Helper 点击“我可以帮助”后必须确认能在截止前完成，可填写安全帮助说明；借物请求还可填写实际品牌和型号。服务在 `BEGIN IMMEDIATE` 中只复核请求开放且未过期、Helper 不是 Requester、能力确认、品牌规则和唯一认领。新响应不依赖 `UserItem`，`HelpOffer.item_id` 可以为空。
- 无偏好或准确满足时直接创建唯一 `accepted` Offer。`exact_only` 拒绝不匹配响应；`ask_before_substitute` 的不匹配响应创建 `proposed` Offer，请求继续开放，直到 Alice 接受后才唯一进入 `matched`；Alice 也可拒绝。`equivalent_ok` 的已确认替代响应可直接认领。首个有效直接认领或首个被 Alice 接受的提案获胜，其余并发操作收到安全冲突或被取消。
- 取消、到期、开始交接和双方完成不得假定 Offer 关联物品。Requester 详情只返回提案所需的 Helper 名称、帮助说明和实际品牌／型号；WebSocket 仍只发送失效通知，HTTP GET 是权威快照。Helper 的隐藏／恢复只影响本人，不进入 Requester 时间线。
- SQLite 升级必须可重复运行，保留旧请求、草稿、Offer 和事件；通过事务内表重建把旧 `help_offers.item_id NOT NULL` 安全迁移为可空，并恢复唯一索引。
- 增加与课堂 LAN 分离的临时公网拍摄模式：Quick Tunnel 只连接 loopback Vite 5173，Vite 继续把 `/api` 和 `/ws` 代理到 loopback FastAPI 8000。后端只接受逐个列出的规范 TryCloudflare HTTPS Origin，Vite 只接受对应具体 hostname；不使用 Host／Origin 通配符，不改变任何匹配、响应、提案、认领或状态机规则。

旧 `UserItem`、Helper 位置、availability、信誉及离线步行图可为历史数据兼容保留，但不再是新响应流程的权威来源。临时公网入口只用于 Mock、虚构数据和短时校园拍摄；课堂正式 Live Demo 仍以自有热点 LAN 为主。

## 不做

公开库存、GPS／实时地图、Helper availability calendar、自动信誉计算、逐人派单、生产认证、精确导航、持久域名／生产 Cloudflare Tunnel、自动安装 cloudflared 或真实 Provider 自动化调用。

## 完成证据

通过 [AT-15 至 AT-22](../ACCEPTANCE_TESTS.md#06-matching-quality--campus-coverage) 和仍适用的 Milestone 01–05 回归。自动化覆盖服务解析与完整闭环、任意物品、G 栋及无预设物品认领、原子草稿确认、品牌规则、替代提案、并发唯一认领、空 `item_id` 的取消／完成、默认隐藏调试入口、重复迁移、WebSocket 与轮询，以及公网 Origin／Host 严格解析、TLS/SNI WSS preflight 和权限无回归。三名组员最终分别用 Alice、Erin、Grace 在三台 LAN 设备完成课堂验收；公网拍摄另用不同网络设备如实记录。全程固定使用 Mock，不调用真实 DeepSeek 或 Ollama。实施分支为 `milestone-06-matching-quality`，验收修正完成前不 commit、push 或 merge。
