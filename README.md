# CampusHands

Milestone 04 adds WebSocket notifications to the deterministic BorrowLoop and Milestone 03 Agent flow. Alice still confirms a formal draft and explicitly starts matching; Bob can decline, Carol can accept, and both parties confirm the handoff. All people and items are fictional.

## Requirements

- Python 3.11 or newer (the commands below use Python 3.14)
- Node.js and npm
- Windows PowerShell

## Start the backend

From the repository root:

```powershell
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL = "sqlite:///./campushands-demo.db"
.\.venv\Scripts\python.exe -m app.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --ws wsproto
```

The backend listens at `http://127.0.0.1:8000`; OpenAPI documentation is at `http://127.0.0.1:8000/docs`. The explicit seed command adds Alice, Bob, Carol, David, their fictional items, and one draft request without duplicating existing records. Use a new `DATABASE_URL` filename for an independent demo; existing SQLite files are preserved. The app checks offer timeouts while it runs and catches up on restart. Keep the server running while starting the frontend in another terminal.

Milestone 04 requires the `wsproto` package declared in `backend/pyproject.toml`; the installation command above installs it. Uvicorn is started with `--ws wsproto` so browser WebSocket upgrades work.

For a completely offline Agent demo, set `$env:LLM_PRIMARY_PROVIDER = "mock"` and `$env:LLM_FALLBACK_PROVIDER = "mock"` before starting Uvicorn. For manual provider testing, copy `backend/.env.example` to the ignored `backend/.env` and add your DeepSeek key there locally; the backend reads the key only from that file. Install and start Ollama separately, and pull `qwen3.5:4b` separately before testing fallback. Never paste or commit the key. The status endpoint reports provider categories and recent call state; it does not make a paid probe.

## Start the frontend

From the repository root in a new PowerShell terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. Vite forwards `/api` and `/ws` to the local backend. Create a scientific calculator request at VA with a deadline at least ten minutes away, open its detail page, and click **开始匹配**. In separate browser tabs, select Bob and Carol in Demo Mode. Bob can decline; Carol's Inbox receives the next Offer without a manual refresh. When Carol accepts, Alice's request page shows `matched` and the ordered public timeline without a manual refresh. Return to Alice, start the handoff and confirm it; then switch to Carol to confirm completion. The connection label shows **实时连接** or **轮询模式**; an unavailable WebSocket falls back to a two-second HTTP poll. A request remains a `draft` until Alice starts matching. The deadline applies to finding a helper; after a match, the handoff may continue. A cancelled match releases the item, while a completed handoff keeps it unavailable.

For the Agent path, enter a natural-language request on the Requester page. If fields are missing, answer the specific clarification question or edit the parsed fields. Confirm the parsed fields to create a formal `draft`, then click **Agent 开始匹配**. The model proposes an allowlisted action; the existing service chooses the helper and records the Offer. After a Helper response or timeout, **Agent 查看下一步** reads the authoritative result without changing it. A failed model call leaves the form usable and returns a retryable error. The existing structured form remains available below the Agent entry.

## Check Milestones 01–04

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

In a separate terminal:

```powershell
cd frontend
npm.cmd run test
npm.cmd run lint
npm.cmd run build
```

If the UI reports that it cannot reach the backend, start FastAPI on port 8000. If no Helper offers appear, run the seed command against the same `DATABASE_URL` used by the server. The seed command never resets an accepted item; use a fresh database filename to repeat the entire demo. Existing Milestone 01/02 records are preserved; initialization adds the Agent draft table and nullable Offer message column. WebSocket subscriptions use a fictional `demo_user_id` query value because browser WebSockets cannot set the HTTP Demo header; neither mechanism is real authentication. The in-memory broadcaster supports only one FastAPI process. Do not commit `.env`, database files, or real student data. Offline tests use Mock and do not contact DeepSeek or Ollama.

## Repository layout

- `backend/`: FastAPI, deterministic matching and state services, Agent/provider adapters, SQLite persistence, demo seed, pytest checks
- `frontend/`: React, Vite, natural-language and structured Requester forms, Helper views with WebSocket notifications and HTTP polling fallback
- `docs/`: product, architecture, workflow, acceptance scenarios, milestones
