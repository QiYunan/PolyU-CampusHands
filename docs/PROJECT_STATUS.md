# CampusHands Project Status

## 1. Current Objective

Milestone 06 is merged into `main` by PR #7. Milestone 07 development is active on `m07-helper-supply-matching` from the shared `milestone-07-supply-first-ux` integration branch. The B-side implementation adds long-term Helper capabilities, Hong Kong-local daily availability, deterministic item/service search, multi-round targeted invitations, atomic first acceptance, private invitation realtime and the two isolated Helper Hall panels. M06 public-board APIs remain for compatibility but are not the M07 default UI path. M07 is **not finally accepted** until integration with developer A and three-physical-device LAN plus Quick Tunnel walkthroughs complete. See [Milestone 07](milestones/07-supply-first-ux.md) and the [M07 API contract](M07_API_CONTRACT.md).

## 2. Completed Milestones

- Milestone 01: structured request creation and persistent SQLite readback.
- Milestone 02: historical serial Offer flow, handoff, and two-party completion. Milestone 06 replaces the serial publication and timeout behavior on its branch.
- Milestone 03: merged into main; Mock browser flow and real DeepSeek/Ollama provider smoke checks passed on the development machine. Credential rotated; redaction regression added.
- Milestone 04: merged into main at `871bc17`; WebSocket notifications and HTTP polling recovery are present, with offline tests and the earlier multi-tab Mock browser flow documented.
- Milestone 06: merged into `main` by PR #7 at `c719cb6`; its open-board flow remains a compatibility surface for M07 regression.

Milestone 05 was merged into `main` by PR #6 at `715f1c0`. Its prior branch report recorded 64 backend tests, 14 frontend tests, frontend lint/build, a fresh-checkout check and a three-tab Mock browser walkthrough; those are historical results, not Milestone 06 verification. The dedicated reset command is limited to the marked `.demo` SQLite file and does not alter the normal development database.

The preceding serial-flow implementation had reported 108 backend tests and 22 frontend tests passing; those are historical results for the superseded Offer flow. On 2026-11-16 the M07 developer-B revision passed 145 backend tests and 34 frontend tests, including targeted-invitation concurrency and private WebSocket authorization, while preserving the M01–M06 suite. Frontend lint/build, `git diff --check`, and the tracked/candidate artifact scan over 99 files also passed. Existing same-host browser contexts are historical M06 evidence only; three separate physical devices, developer-A integration and a live Quick Tunnel across different networks remain untested. No cloudflared process was started and no real Provider call was made.

## 3. Current Architecture

React/Vite uses HTTP for authoritative snapshots and WebSocket notifications for realtime updates. FastAPI services own SQLite data, daily supply, deterministic candidate selection, invitation rounds, atomic acceptance, permissions and state. The Agent may request the shared search service but cannot choose a Helper or make an acceptance authoritative. Classroom LAN and temporary public Origins remain separate explicit allowlists. DeepSeek is the configured primary model, local Ollama the fallback, and MockLLMProvider the offline test provider; automated acceptance uses Mock only. See [architecture](ARCHITECTURE.md).

## 4. Known Issues and Bugs

1. Demo role switching is not production authentication; real student data must not be used.
2. Real provider availability and Ollama model output can vary by machine; the development-machine smoke checks do not replace offline CI.
3. The in-memory realtime manager, single-process deadline checker and SQLite are suitable for the local demo, not a multi-worker deployment.
4. Static campus walking links and minutes are project estimates; building and footbridge access arrangements can change. They are neither live navigation nor a guarantee of access.
5. Quick Tunnel is a temporary testing service with a changing URL, no availability guarantee, a 200 in-flight request limit and no SSE support. Anyone holding the URL can access the fictional Demo while it is running; it is not authentication or a production deployment.

## 5. Next Decision

Merge the developer B branch into the M07 integration branch after review, then let developer A consume the frozen contract and mount the two exported Helper panels beside “找 Helper”. Run the three-device targeted-invitation flow on one LAN/hotspot and the separate Mock-only Quick Tunnel walkthrough. Preserve existing ignored Demo data, do not install cloudflared automatically, and do not merge the M07 integration branch to `main` until physical acceptance and user review are recorded.
