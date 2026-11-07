# Contributing to CampusHands

Work on a feature branch and open a Pull Request into `main`; do not develop directly on `main`. Read [AGENTS.md](AGENTS.md), the [Milestone 05 scope](docs/milestones/05-demo-hardening.md) and the relevant product/architecture/acceptance document before editing. Keep each fact in its owning document and link from other documents.

## Local Mock development

Follow [README.md](README.md) from a clean checkout. Set `LLM_PRIMARY_PROVIDER=mock` and `LLM_FALLBACK_PROVIDER=mock` in the backend terminal before starting it. Mock Recovery Mode is an offline simulation and must remain clearly labelled. CI never receives DeepSeek or Ollama secrets and never calls either real provider.

Before asking for review, run backend `python -m pytest -q`, frontend `npm run test`, `npm run lint`, `npm run build`, `python scripts/check_tracked_artifacts.py`, and `git diff --check`. Record any check that was not run. For user-facing changes, rehearse the [Demo runbook](docs/DEMO_RUNBOOK.md) and check the matching [acceptance scenarios](docs/ACCEPTANCE_TESTS.md).

Do not commit `.env`, database files, logs, model files or real student data. Keep a real DeepSeek key only in the ignored `backend/.env`. Do not paste keys into PRs, screenshots or test output. The Demo role switcher is fictional and is not production authentication.
