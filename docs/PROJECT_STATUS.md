# CampusHands Project Status

## 1. Current Objective

Milestone 03 adds a bounded Agent experience to the established BorrowLoop: natural-language parsing, clarification, user confirmation, controlled tool proposals, and provider recovery. See [Milestone 03](milestones/03-agent-integration.md).

## 2. Completed Milestones

- Milestone 01: structured request creation and persistent SQLite readback.
- Milestone 02: deterministic matching, Offer responses and timeout, handoff, and two-party completion.
- Milestone 03: implementation is under review; Mock browser flow and real DeepSeek/Ollama provider smoke checks passed on the development machine. Credential rotated; redaction regression added.

## 3. Current Architecture

React/Vite uses HTTP to reach FastAPI. FastAPI services own SQLite data, matching, permissions, state and timeouts. The Agent layer may propose only validated service actions. DeepSeek is the primary model, local Ollama the fallback, and MockLLMProvider the offline test provider. See [architecture](ARCHITECTURE.md).

## 4. Known Issues and Bugs

1. Demo role switching is not production authentication; real student data must not be used.
2. Real provider availability and Ollama model output can vary by machine; the development-machine smoke checks do not replace offline CI.
3. The single-process timeout checker and SQLite are suitable for the local demo, not a multi-worker deployment.

## 5. Next Decision

Review this status document and Milestone 03 verification results before approving its final wording or a merge. WebSocket updates remain Milestone 04.
