# CampusHands Project Status

## 1. Current Objective

Milestone 04 adds realtime notifications to the established BorrowLoop and Agent experience. See [Milestone 04](milestones/04-realtime-updates.md).

## 2. Completed Milestones

- Milestone 01: structured request creation and persistent SQLite readback.
- Milestone 02: deterministic matching, Offer responses and timeout, handoff, and two-party completion.
- Milestone 03: merged into main; Mock browser flow and real DeepSeek/Ollama provider smoke checks passed on the development machine. Credential rotated; redaction regression added.
- Milestone 04: implementation is under review; local offline tests and the multi-tab Mock browser flow passed, including WebSocket loss and HTTP polling recovery.

## 3. Current Architecture

React/Vite uses HTTP for authoritative snapshots and WebSocket notifications for realtime updates. FastAPI services own SQLite data, matching, permissions, state and timeouts. The Agent layer may propose only validated service actions. DeepSeek is the primary model, local Ollama the fallback, and MockLLMProvider the offline test provider. See [architecture](ARCHITECTURE.md).

## 4. Known Issues and Bugs

1. Demo role switching is not production authentication; real student data must not be used.
2. Real provider availability and Ollama model output can vary by machine; the development-machine smoke checks do not replace offline CI.
3. The in-memory realtime manager, single-process timeout checker and SQLite are suitable for the local demo, not a multi-worker deployment.

## 5. Next Decision

Review Milestone 04 verification results and this status document before approving its final wording or a merge. Demo subscriptions are not production authentication.
