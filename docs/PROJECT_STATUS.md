# CampusHands Project Status

## 1. Current Objective

Milestone 05 hardens the local classroom Demo and clean-checkout collaboration flow. See [Milestone 05](milestones/05-demo-hardening.md) and the [Demo runbook](DEMO_RUNBOOK.md).

## 2. Completed Milestones

- Milestone 01: structured request creation and persistent SQLite readback.
- Milestone 02: deterministic matching, Offer responses and timeout, handoff, and two-party completion.
- Milestone 03: merged into main; Mock browser flow and real DeepSeek/Ollama provider smoke checks passed on the development machine. Credential rotated; redaction regression added.
- Milestone 04: merged into main at `871bc17`; WebSocket notifications and HTTP polling recovery are present, with offline tests and the earlier multi-tab Mock browser flow documented.

Milestone 05 implementation is on `milestone-05-demo-hardening` for review. Local verification passed: 64 backend tests, 14 frontend tests, frontend lint/build, a fresh-checkout install and repeat of the full suites, and a three-tab Mock browser walkthrough in 15.1 seconds. A separate headless run confirmed HTTP polling after WebSocket failure and state recovery after refresh. An approved real-provider smoke check parsed a fictional request through DeepSeek and submitted a validated `send_help_offer` through DeepSeek; it used six DeepSeek requests in total and did not activate Ollama or Mock. The dedicated reset command is limited to the marked `.demo` SQLite file; it does not alter the normal development database. GitHub-hosted CI and a human-timed live presentation have not run on this uncommitted branch.

## 3. Current Architecture

React/Vite uses HTTP for authoritative snapshots and WebSocket notifications for realtime updates. FastAPI services own SQLite data, matching, permissions, state and timeouts. The Agent layer may propose only validated service actions. DeepSeek is the primary model, local Ollama the fallback, and MockLLMProvider the offline test provider. See [architecture](ARCHITECTURE.md).

## 4. Known Issues and Bugs

1. Demo role switching is not production authentication; real student data must not be used.
2. Real provider availability and Ollama model output can vary by machine; the development-machine smoke checks do not replace offline CI.
3. The in-memory realtime manager, single-process timeout checker and SQLite are suitable for the local demo, not a multi-worker deployment.

## 5. Next Decision

Review the Milestone 05 test results, timed Mock browser flow and clean-checkout evidence before a Pull Request or merge. Demo subscriptions remain fictional identity checks, not production authentication.
