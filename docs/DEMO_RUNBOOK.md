# CampusHands Demo runbook

本页维护课堂演示步骤；产品与状态规则见 [产品规格](PRODUCT_SPEC.md)、[Agent 工作流](AGENT_WORKFLOW.md) 和 [验收场景](ACCEPTANCE_TESTS.md)。Demo Mode 使用虚构身份，不是正式登录或生产认证。

## 临时公网拍摄模式（Quick Tunnel）

该模式只用于短时测试和校园实拍，让处于不同网络的 Alice 与 Helper 使用同一个随机 HTTPS 地址。课堂正式 Live Demo 仍以自有热点 LAN 为主。Quick Tunnel 没有可用性保证，地址每次启动都会变化，地址持有者都可以访问 Demo；只能使用虚构身份和虚构数据，不得输入真实学号、密码、电话或个人资料。Vite 开发服务器的前端开发内容会被临时公开，开发电脑必须保持联网、开机且禁止睡眠。完全断网时该模式不可用。

Quick Tunnel 最多支持 200 个 in-flight 请求，不支持 SSE；CampusHands 当前使用 WebSocket 失效通知和两秒 HTTP GET 轮询，不依赖 SSE。详见 [Cloudflare Quick Tunnel 限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。项目不自动下载或安装 `cloudflared`，也不会自动重命名、删除或修改用户的 Cloudflare 配置。

### 准备与启动顺序

1. 先按 README 的本机流程使用 Mock 和隔离 `backend/.demo/campushands.db`：在服务停止时先 reset，再执行 setup preflight；随后以 FastAPI `127.0.0.1:8000`、Vite `127.0.0.1:5173` 启动并执行本机 ready preflight。确认首页、`/api`、Helper-board WebSocket 和 Mock provider 全部正常；不得用公网模式掩盖本机故障。
2. 在新的 PowerShell 终端确认 `cloudflared` 已由用户预先安装，然后保持 Vite 运行并启动：

   ```powershell
   cloudflared tunnel --url http://127.0.0.1:5173
   ```

   记录终端打印的完整随机 URL，例如 `https://exact-name.trycloudflare.com`，并从中提取精确 hostname `exact-name.trycloudflare.com`。不要使用根域、通配符、路径或自定义端口。
3. 保持 cloudflared 进程运行，停止后端和 Vite。在这段重启窗口里，公网 URL 可能暂时返回 502，这是 Vite 尚未监听 5173 的预期现象。
4. 在之后用于启动后端和执行 preflight 的后端终端设置完整 Origin；在启动 Vite 的前端终端设置只有 hostname 的 allowlist。多个临时地址都必须在两边逐个完整列出并形成相同集合，不能使用 `.trycloudflare.com` 后缀匹配：

   ```powershell
   # backend / preflight terminals
   $env:CAMPUSHANDS_PUBLIC_DEMO_ORIGINS = "https://exact-name.trycloudflare.com"

   # frontend terminal
   $env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = "exact-name.trycloudflare.com"
   ```

5. 保持 8000 和 5173 仍为空闲时，从 `backend` 执行公网 setup：

   ```powershell
   $env:DATABASE_URL = "sqlite:///./.demo/campushands.db"
   $env:LLM_PRIMARY_PROVIDER = "mock"
   $env:LLM_FALLBACK_PROVIDER = "mock"
   .\.venv\Scripts\python.exe -m app.demo preflight --stage setup --mode mock --public-url https://exact-name.trycloudflare.com
   ```

   setup 会验证 URL、两个环境变量的逐项一致性、Vite 的具体 hostname、`cloudflared` 命令和隔离数据库。若用户目录存在 `.cloudflared/config.yaml` 或 `config.yml`，会输出 `WARN`，因为该配置可能阻止 Quick Tunnel；preflight 不读取或修改该文件。缺少 `cloudflared` 会明确 `FAIL`，不会自动安装。
6. 用 loopback 重新启动后端和 Vite；只有 cloudflared 连接 Vite：

   ```powershell
   # backend
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --ws wsproto --host 127.0.0.1 --port 8000

   # frontend
   npm.cmd run dev
   ```

   不要把 FastAPI 改为 `0.0.0.0`，不要把 Tunnel 指向 8000，也不要公开 Ollama 11434、SQLite 或其他端口。无需也不得新增 CORS。Vite `/ws` 代理必须保留浏览器的 `Origin: https://exact-name.trycloudflare.com`，不得启用 `rewriteWsOrigin`。
7. 从单独的后端终端执行公网 ready：

   ```powershell
   .\.venv\Scripts\python.exe -m app.demo preflight --stage ready --mode mock --public-url https://exact-name.trycloudflare.com
   ```

   ready 必须通过公网 HTTPS 首页、同一 Origin 下的 `/api/system/health`，以及带合法 `demo_user_id` 和 HTTPS Origin 的真实 TLS/SNI Helper-board WSS upgrade。该检查只握手并关闭，不发布、认领或修改业务数据，也不读取 `backend/.env` 或调用真实模型。
8. 全部 PASS 后才把完整 HTTPS 地址发给参与拍摄的队友。公网浏览器自动使用 `wss`；FastAPI 继续核验 Requester、Helper 与资源权限。WebSocket 只发送失效通知，GET 仍是权威状态，断线后页面每两秒轮询。通知不含库存、位置、候选数、评分、密钥或模型输出。

### 拍摄与关闭验收

1. 一台电脑保持 FastAPI、Vite、隔离 SQLite 和 cloudflared 运行。Alice 从一个网络通过公网 HTTPS 发布；手机 Helper 使用与电脑不同的网络打开同一地址，无需刷新看到请求、确认能力并响应；Alice 实时看到 `matched`，双方完成交接。
2. 主动断开一个页面的业务 WebSocket，确认页面进入轮询模式且仍能通过两秒 GET 同步。
3. 拍摄结束立即停止 cloudflared，保留旧 URL 并从另一网络确认它已不可访问。不要把停止 Vite 或断开开发电脑网络误当作单独证明；目标是确认 Tunnel 进程停止后 URL 失效。
4. 停止使用隔离数据库的后端，再执行 `python -m app.demo reset`。关闭或换用新终端以清除两个公网环境变量；随后复验本机模式。课堂 LAN 模式仍按下一节使用 `0.0.0.0` 和独立的 `CAMPUSHANDS_LAN_ORIGINS`，不要求公网 Origin 或 cloudflared。

## 三设备局域网准备

1. 三台设备连接同一手机热点或允许设备互访的局域网。托管电脑查看自己的 RFC1918 IPv4 地址（例如 `192.168.43.21`）；如学校 Wi-Fi 隔离设备，改用手机热点。本机三个独立浏览器窗口是备用方案。
2. 使用隔离的 `backend/.demo/campushands.db`，在**停止使用该库的后端后**运行 `python -m app.demo reset`。该命令只重建带标记的 Demo 库；已有预览或演示数据不要在进行中重置。设置 `DATABASE_URL=sqlite:///./.demo/campushands.db`，并把两个 LLM provider 都设为 `mock`。本次验收不使用真实 DeepSeek 或 Ollama。
3. 在托管电脑的后端终端显式设置 `$env:CAMPUSHANDS_LAN_ORIGINS = "http://192.168.43.21:5173"`，将示例地址换成托管电脑实际地址。多课堂地址用逗号分隔；只接受明确的 RFC1918 `http://IP:5173`，不使用 `*`。前端终端用同一地址配置，以便 preflight 一起检查。
4. 后端从 `backend` 启动：`python -m uvicorn app.main:app --ws wsproto --host 0.0.0.0 --port 8000`。前端从 `frontend` 启动：`npm.cmd run dev -- --host 0.0.0.0`。托管电脑和其他设备都打开 `http://192.168.43.21:5173`；不要把 Ollama 或数据库端口暴露到 LAN。Windows 防火墙需要允许当前私有网络的 8000、5173 入站连接。
5. 启动前运行 `python -m app.demo preflight --stage setup --mode mock`，启动后运行 `python -m app.demo preflight --stage ready --mode mock`。若 setup 报端口占用，先确认是否为预期进程；ready 应显示实际 LAN URL、前后端 HTTP 可达、Helper 广场 WebSocket 握手及 Mock provider 状态。preflight 只作只读探测，不向真实 provider 发请求。请在三台设备各自打开页面验证网络，不把托管电脑的本地检查当作手机端可达性的证明。
6. A 选 `Alice · Requester`，B 选 `Erin · Helper`，C 选 `Grace · Helper`。确认两个 Helper 广场只显示各自姓名且没有请求；默认页面不显示预设库存、当前位置、availability 或结构化调试表单。角色来自 `GET /api/demo/roles`，不应出现“演示角色5”等编号菜单。

完整的本地安装和 Mock 命令见 [README](../README.md)。如果没有手机或独立电脑，在托管机打开三个独立浏览器窗口进行同样演示。

## 课堂主流程

| 阶段 | A：Alice | B：Erin | C：Grace | 预期权威状态 |
| --- | --- | --- | --- | --- |
| 解析与确认 | 输入“30分钟之后，在Z栋交接，需要一台Casio计算器”；在同一表单核对需求摘要、Z、Casio、截止时间、紧急程度和替代规则，直接点“确认并创建请求” | 等待，保持广场打开 | 等待，保持广场打开 | confirm 一次提交当前全部字段；正式请求为 `draft`，没有 Offer。 |
| 发布 | 启动受控 Agent，展示经过 schema 验证的 `publish_request` 工具名称 | 无需刷新，看到同一求助 | 无需刷新，看到同一求助 | 请求为 `awaiting_response`；时间线只写“已解析并确认”“请求已发布”等关键事件。 |
| 并发认领 | 观察请求页 | 点击“我可以帮助”，勾选能按时完成，填写实际品牌／型号后确认 | 几乎同时执行相同确认 | 服务以 `BEGIN IMMEDIATE` 复核开放状态、能力确认和品牌规则。恰好一人成功，另一人收到安全 409；仅一条 `accepted` Offer。 |
| 实时关闭 | 页面显示成功认领者和 `matched` | 广场自动关闭该请求 | 广场自动关闭该请求 | 广场 WebSocket 只通知变化，客户端 GET 权威快照；没有逐人 30 秒邀请超时事件。 |
| 双方完成 | 开始交接并确认完成 | 获胜者确认完成 | 若未获胜，仅观察关闭状态 | 第一方确认后仍为 `in_progress`；双方都确认后为 `completed`。 |

成功者可能是 Erin 或 Grace，不需人为安排顺序。广场对 Bob、Carol 等其他 Demo Helper 同时可见且按钮可点击；是否能按时完成由本人确认，预设库存或位置不控制响应。

## 补充验收

- **替代品提案：**用 `Casio`、`fx-991cnx`、`ask_before_substitute` 创建并发布借物请求。Helper 在确认弹窗选择替代方式并填写不同品牌／型号；服务创建 `proposed` Offer，请求保持开放。Alice 的详情页显示安全帮助说明和实际品牌／型号；接受后才 `matched`，拒绝后仍开放。另用 `exact_only` 验证不匹配响应被拒绝。
- **服务：**Alice 输入“20分钟后，在Z栋，需要同学帮我搬运实验器材，有偿”，确认解析为 `service` 且无品牌／型号字段。选择一个没有对应预设物品的 Helper，确认能力后响应并完成双方确认；Offer 可无 `item_id`。
- **暂不参与：**一名 Helper 点击“暂不参与”，其本人广场隐藏该请求，其他 Helper 仍看到且可认领；本人“恢复”后重新出现。Alice 时间线没有该动作。
- **自主响应：**用 G 栋请求、无预设同类物品、Helper 预设位置很远或 availability 非 available 的固定数据验证：开放请求仍显示且按钮可点击；服务只依据本人能力确认、请求状态、截止时间和品牌规则。
- **地点：**`Z栋`、`Z座`、`Block Z` 都解析为 Z；`Library`、`图书馆`、`圖書館` 都解析为 L。未知地点留在澄清，不发布、不创建 Offer。地点 registry 不判断 Helper 能否到达。
- **断线恢复：**人为断开一个 Helper 页的 WebSocket，页面应进入轮询提示；发布或认领后仍通过 HTTP GET 对齐。刷新或重开请求 URL 后状态与事件不重复。

## 故障恢复

| 情况 | 操作 |
| --- | --- |
| 另一设备无法打开 LAN URL | 检查热点同网、托管机 IPv4、Windows 私有网络防火墙和 Vite／Uvicorn 的 `0.0.0.0` 监听；改用三独立浏览器窗口。 |
| WebSocket 连接中断 | 等待两秒轮询 GET；恢复连接后再 GET。通知丢失不能改变服务端认领结果。 |
| 两人同时点击，一人收到 409 | 这是预期结果；该页面重新读取广场和请求状态，不重试占用的请求。 |
| 后端重启或页面刷新 | 重新打开已有请求 URL；GET 从 SQLite 恢复状态。已发布请求无个人邀请倒计时。 |
| Demo 数据异常 | 结束当前演示、停止使用 Demo 库的后端，之后才 reset 并重做 preflight。 |
| Mock provider 失败 | 展示错误和服务端请求状态；不要声称 AI 解析成功。默认界面不暴露结构化调试入口；开发者仅可在启动前显式设置 `VITE_SHOW_STRUCTURED_DEBUG_FORM=true` 用于受控测试。 |

公开时间线只记录已提交的请求、响应／提案接受和交接事件；模型原文、工具参数、预设库存、Helper 位置、availability、步行估算及信誉度不进入时间线或广场通知。Requester 仅在有人主动提交提案后看到该响应者的安全说明与实际品牌／型号。
