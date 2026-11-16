# CampusHands

CampusHands is a fictional PolyU mutual-help demo for both item borrowing and campus services. Alice describes a need, the Agent may propose a schema-validated publication action, and the deterministic service controls location validation, response rules, atomic claims and completion. Every Helper sees each open request and decides whether they can meet the deadline; preset inventory, saved location, availability and walking-time estimates do not control the response button. Demo Mode is not student authentication.

The timed walkthrough, recovery steps and known limits are in the [Demo runbook](docs/DEMO_RUNBOOK.md). Development rules are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Requirements

- Windows PowerShell, Python 3.11+, Node 24 (the locally verified version; Vite also accepts compatible Node 20.19+ or 22.12+)
- No Docker or cloud deployment
- Milestone 06 development and acceptance use Mock Recovery Mode, which works offline and is always labelled as a simulation. Real-provider testing requires separate approval.
- `cloudflared` is optional and is never installed by this project. It is used only for the temporary public filming mode described below.

## Start from a clean checkout

Use three PowerShell terminals. The commands below start in the repository root and use Mock only. The `reset` command does not open `backend/.env`.

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

Open `http://127.0.0.1:5173`. The UI must visibly say **Mock Recovery Mode**. Both preflight stages return exit code 1 for blocking failures, so check that each prints only `PASS` or non-blocking `WARN` before the timed demo. The ready stage verifies FastAPI health, the frontend port, an authorized Helper-board WebSocket upgrade and provider status without calling a model.

For the three-device classroom flow, use one computer as host and put all three devices on the same hotspot or LAN. In the **backend** terminal set `$env:CAMPUSHANDS_LAN_ORIGINS = "http://192.168.43.21:5173"` using the host's real private-network IPv4 address. Set the same variable in the **preflight** terminal. Start Uvicorn with `--host 0.0.0.0`; start Vite with `npm.cmd run dev -- --host 0.0.0.0`. Every device opens `http://192.168.43.21:5173`. The Origin list must name each allowed full `http://IP:5173` URL explicitly; wildcard or public-IP Origins are rejected. Preflight prints the LAN URL and checks local and LAN HTTP plus a Helper-board WebSocket handshake. See the [classroom runbook](docs/DEMO_RUNBOOK.md) for the complete three-device procedure. Do not reset an active Demo database or stop an existing preview solely to rehearse.

For short campus filming across different networks, an already installed `cloudflared` may temporarily expose **only Vite** with `cloudflared tunnel --url http://127.0.0.1:5173`. After it prints a random `https://...trycloudflare.com` URL, stop and restart the backend and Vite with the exact URL in `CAMPUSHANDS_PUBLIC_DEMO_ORIGINS` and its hostname in `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS`; keep both services on `127.0.0.1`. Run both preflight stages with `--mode mock --public-url <exact URL>` before sharing it. The browser continues to use Vite's same-origin `/api` and `/ws` proxies; port 8000, Ollama, SQLite and other local ports are not tunneled. Stop the Tunnel immediately after filming, confirm the URL no longer works, then stop the backend and reset the isolated Demo database. The exact commands, 502 restart window and safety limits are in the [temporary public filming procedure](docs/DEMO_RUNBOOK.md#临时公网拍摄模式quick-tunnel).

The backend's normal development database is `backend/campushands.db`. The timed demo uses only `backend/.demo/campushands.db`, explicitly selected by `DATABASE_URL`. Stop the backend before each reset; a process lock also refuses reset while any backend is using that Demo database, even on another port. Reset recreates only this marked database with Alice and 11 fictional Helpers plus legacy inventory fixtures. It begins with no request, draft, Offer, dismissal or event. The older `python -m app.seed` remains available for additive fixtures; it is not a reset. The offline location registry validates and normalizes the Requester's handoff location; legacy walking estimates are not used to decide whether a Helper may respond. See [Milestone 06](docs/milestones/06-matching-quality.md).

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
