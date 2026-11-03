# CampusHands

Milestone 01 provides a local demo loop: Alice creates a structured borrowing request, FastAPI stores it in SQLite as `draft`, and the browser reloads it by ID. Matching, helper offers, LLM providers, and WebSocket updates belong to later milestones.

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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The backend listens at `http://127.0.0.1:8000`. API documentation is at `http://127.0.0.1:8000/docs`. On first startup it creates `backend/campushands.db` and the local Alice demo user. Restarting does not erase requests. To use another database path, set `DATABASE_URL` to a SQLite URL before starting the backend. Keep the server running while starting the frontend in another terminal.

## Start the frontend

From the repository root in a new PowerShell terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. Vite forwards `/api` to the local backend. Enter an item, location, and future deadline; the saved request opens at `/requests/{id}`. Reopen that URL or restart the backend to confirm persistence.

## Check Milestone 01

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

If the UI reports that it cannot reach the backend, start FastAPI on port 8000. If an old SQLite schema is present from an experimental run, use a fresh database URL; this milestone does not include schema migrations. Do not commit `.env`, database files, or real student data.

## Repository layout

- `backend/`: FastAPI, SQLAlchemy models, SQLite persistence, pytest checks
- `frontend/`: React, Vite, structured form and request detail page
- `docs/`: product, architecture, workflow, acceptance scenarios, milestones
