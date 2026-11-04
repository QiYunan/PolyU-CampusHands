# CampusHands

Milestone 02 adds a deterministic BorrowLoop flow to the Milestone 01 request form. Alice starts matching from a saved draft; Bob can decline, Carol can accept, and both parties confirm the handoff. All people and items are fictional. LLM providers and WebSocket updates belong to later milestones.

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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The backend listens at `http://127.0.0.1:8000`; OpenAPI documentation is at `http://127.0.0.1:8000/docs`. The explicit seed command adds Alice, Bob, Carol, David, their fictional items, and one draft request without duplicating existing records. Use a new `DATABASE_URL` filename for an independent demo; existing SQLite files are preserved. The app checks offer timeouts while it runs and catches up on restart. Keep the server running while starting the frontend in another terminal.

## Start the frontend

From the repository root in a new PowerShell terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. Vite forwards `/api` to the local backend. Create a scientific calculator request at VA with a deadline at least ten minutes away, open its detail page, and click **开始匹配**. Switch Demo Mode to Bob and decline his offer; switch to Carol and accept hers. Return to Alice, start the handoff and confirm it; then switch to Carol to confirm completion. The public timeline is refreshed through HTTP polling. A request remains a `draft` until Alice starts matching. The deadline applies to finding a helper; after a match, the handoff may continue. A cancelled match releases the item, while a completed handoff keeps it unavailable.

## Check Milestones 01 and 02

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

If the UI reports that it cannot reach the backend, start FastAPI on port 8000. If no Helper offers appear, run the seed command against the same `DATABASE_URL` used by the server. The seed command never resets an accepted item; use a fresh database filename to repeat the entire demo. Existing Milestone 01 tables and requests are kept when the new tables are created. Demo role headers are not real authentication. Do not commit `.env`, database files, or real student data.

## Repository layout

- `backend/`: FastAPI, deterministic matching and state services, SQLite persistence, demo seed, pytest checks
- `frontend/`: React, Vite, Requester and Helper views with HTTP polling
- `docs/`: product, architecture, workflow, acceptance scenarios, milestones
