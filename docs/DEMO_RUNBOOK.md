# CampusHands Demo runbook

This page owns the timed classroom procedure. The architecture and provider boundaries are documented in [ARCHITECTURE](ARCHITECTURE.md) and [AGENT_WORKFLOW](AGENT_WORKFLOW.md); current deployment limits are in [PROJECT_STATUS](PROJECT_STATUS.md).

## Before the timer

1. Use the [README startup steps](../README.md). Confirm branch and clean worktree, install dependencies, stop the backend, run `python -m app.demo reset`, then run `preflight --stage setup` and `preflight --stage ready` with the selected mode. Both must exit 0.
2. For real mode, check that DeepSeek is configured and local Ollama serves `qwen3.5:4b`. A configuration check is not a successful model call. Rehearse twice with fictional input and time each run. If either path is slow or unreliable, restart in visibly labelled **Mock Recovery Mode** and reset again before the timer. Mock is an offline simulation, never evidence of a real model response.
3. Pre-open Alice's Requester page and Bob's and Carol's Helper Inbox in separate tabs. Keep the request tab URL after creation. Confirm System Status and either “实时连接” or “轮询模式”. Do not edit code, keys or environment variables during the timed run.

## Timed script — 4:00 content plus 0:30 buffer

| Time | Presenter action | Expected UI | Recovery on stage |
| --- | --- | --- | --- |
| 0:00–0:20 | Explain the urgent campus borrowing problem and fictional Demo Mode. | Alice's Requester page is visible. | Move directly to Alice's example. |
| 0:20–1:10 | Enter “我20分钟后在VA考试，想借一部科学计算器”; check item, VA, deadline and high urgency; confirm. | Parsed fields appear, then a formal `draft` request. | If parsing fails, show the provider status. Only a mode selected before the timer may continue the Agent demonstration. |
| 1:10–1:45 | Click **Agent 开始匹配**. | Result card names the provider and locally validated `send_help_offer`; service status becomes `awaiting_response`, Bob gets one Offer. | Read the request page again before retrying. No duplicate Offer is created. |
| 1:45–2:15 | Bob declines in his Inbox. | Bob shows `declined`; Carol's Inbox receives the next Offer without manual refresh. | If the socket is down, point out the two-second polling label and wait for HTTP reconciliation. |
| 2:15–2:50 | Carol accepts; switch to Alice. | Alice shows `matched`, Carol and the ordered public timeline. | Refresh Alice's direct request URL. |
| 2:50–3:35 | Alice starts the handoff and confirms; Carol confirms. | The request stays `in_progress` after only Alice's confirmation, then becomes `completed`. | Refresh each page to inspect the server-owned state. |
| 3:35–4:00 | Show System Status and briefly explain browser → FastAPI → service/SQLite, with the provider proposing only allowed actions. | DeepSeek primary and Ollama fallback, or clearly labelled Mock Recovery Mode, are visible. | Use the architecture summary above. |
| 4:00–4:30 | Buffer. | Allow for loading or tab switching. | Do not change code or environment settings on stage. |

## Recovery matrix

| Situation | Action |
| --- | --- |
| DeepSeek call fails; Ollama works | Existing model-only retry and Ollama fallback run automatically. Show the fallback label and the authoritative request state. |
| Ollama is stopped or `qwen3.5:4b` is absent | Preflight fails with the missing service/model. Start or install it before the timer, or preselect labelled Mock mode. No silent Mock fallback. |
| Both real providers fail during the timed run | Show the retryable error and System Status. A structured request can still demonstrate BorrowLoop, but it is not AI parsing; the Agent acceptance run must be repeated after recovery. |
| WebSocket disconnects | The page shows “轮询模式 · 每 2 秒更新”; HTTP GET remains authoritative and reconnects are deduplicated. |
| Backend restarts or browser refreshes | Restart the backend, reopen the direct request URL or saved draft tab, and let GET reconcile state. The backend catches up due Offer timeouts. |
| Demo data is abnormal | Stop the backend, reset the isolated Demo database, restart and rerun both preflight stages before beginning a new timed run. |
| Port 8000 or 5173 is occupied | Preflight reports the port and available PID. Identify and stop only the known process before the timer; Vite will not silently change ports. |

The acceptance evidence is [AT-13 and AT-14](ACCEPTANCE_TESTS.md#05-演示与协作). The public timeline contains understandable committed events, never model prompts, raw responses, tool arguments or hidden reasoning.
