# CampusHands

CampusHands is a fictional PolyU BorrowLoop demo. Alice asks to borrow an item, the Agent may propose a validated action, and the deterministic service controls matching, offers and completion. Bob can decline, Carol can accept, and both parties confirm the handoff. Demo Mode is not student authentication.

The timed walkthrough, recovery steps and known limits are in the [Demo runbook](docs/DEMO_RUNBOOK.md). Development rules are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Requirements

- Windows PowerShell, Python 3.11+, Node 24 (the locally verified version; Vite also accepts compatible Node 20.19+ or 22.12+)
- No Docker or cloud deployment
- DeepSeek and local Ollama only for a real-provider rehearsal. Mock Recovery Mode works completely offline and is always labelled as a simulation.

## Start from a clean checkout

Use three PowerShell terminals. The commands below start in the repository root. Keep secrets only in the ignored `backend/.env`; never put them in the frontend or a command log. The `reset` command does not open that file.

**Terminal A — install, reset and start the backend**

```powershell
cd frontend
node --version
npm.cmd ci
cd ..
cd backend
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL = "sqlite:///./.demo/campushands.db"
.\.venv\Scripts\python.exe -m app.demo reset
$env:LLM_PRIMARY_PROVIDER = "mock"
$env:LLM_FALLBACK_PROVIDER = "mock"
.\.venv\Scripts\python.exe -m app.demo preflight --stage setup --mode mock
.\.venv\Scripts\python.exe -m uvicorn app.main:app --ws wsproto --host 127.0.0.1 --port 8000
```

**Terminal B — frontend**

```powershell
cd frontend
npm.cmd run dev
```

**Terminal C — running-service checks**

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./.demo/campushands.db"
.\.venv\Scripts\python.exe -m app.demo preflight --stage ready --mode mock
```

Open `http://127.0.0.1:5173`. The UI must visibly say **Mock Recovery Mode**. Both preflight stages return exit code 1 for blocking failures, so check that each prints only `PASS` or non-blocking `WARN` before the timed demo. The ready stage verifies FastAPI health, the frontend port, an authorized WebSocket upgrade and provider status without calling a model.

For a **real-provider** rehearsal, use a fresh backend terminal without the two Mock environment variables. Put the DeepSeek key in the ignored `backend/.env` locally and start Ollama with `qwen3.5:4b` installed. Run both preflight commands with `--mode real` before the timer. The setup check reports only whether a local config file exists; the ready check reports backend configuration and recent call state, never the key. Preflight does not make a paid DeepSeek request. If the real path is unstable, stop the backend and select the labelled Mock configuration **before** the timed demo; never switch provider mode during it.

The backend's normal development database is `backend/campushands.db`. The timed demo uses only `backend/.demo/campushands.db`, explicitly selected by `DATABASE_URL`. Stop the backend before each reset; a process lock also refuses reset while any backend is using that Demo database, even on another port. Reset recreates only this marked database with Alice, Bob, Carol, David and three items. It begins with no request, draft, Offer or event. The older `python -m app.seed` remains available for legacy additive fixtures; it is not a reset.

## Offline checks

```powershell
cd backend
$env:LLM_PRIMARY_PROVIDER = "mock"
$env:LLM_FALLBACK_PROVIDER = "mock"
.\.venv\Scripts\python.exe -m pytest -q
```

```powershell
cd frontend
npm.cmd run test
npm.cmd run lint
npm.cmd run build
```

From the repository root, run `py scripts/check_tracked_artifacts.py` to check candidate Git files without reading ignored `.env` or database files. The same checks run in [offline CI](.github/workflows/ci.yml). Do not use real student data or commit secrets, SQLite databases, logs or model files.
