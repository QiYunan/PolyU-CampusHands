# CampusHands Project Status

## 1. Current Objective

Milestone 06 implementation, including the optional Cloudflare temporary public filming mode, is locally complete on the uncommitted `milestone-06-matching-quality` branch. The branch replaces the serial 30-second Offer flow and preset-inventory qualification with an open Helper board, self-declared capability and atomic first-valid claim. It also permits an explicitly allowlisted random TryCloudflare HTTPS Origin to reach only loopback Vite while preserving FastAPI WebSocket permissions. Automated and same-host browser acceptance pass; the revised milestone remains **not finally accepted** until the three-physical-device classroom LAN walkthrough, the different-network public filming walkthrough and user review. See [Milestone 06](milestones/06-matching-quality.md), [acceptance scenarios](ACCEPTANCE_TESTS.md#06-matching-quality--campus-coverage), and the [Demo runbook](DEMO_RUNBOOK.md).

## 2. Completed Milestones

- Milestone 01: structured request creation and persistent SQLite readback.
- Milestone 02: historical serial Offer flow, handoff, and two-party completion. Milestone 06 replaces the serial publication and timeout behavior on its branch.
- Milestone 03: merged into main; Mock browser flow and real DeepSeek/Ollama provider smoke checks passed on the development machine. Credential rotated; redaction regression added.
- Milestone 04: merged into main at `871bc17`; WebSocket notifications and HTTP polling recovery are present, with offline tests and the earlier multi-tab Mock browser flow documented.

Milestone 05 was merged into `main` by PR #6 at `715f1c0`. Its prior branch report recorded 64 backend tests, 14 frontend tests, frontend lint/build, a fresh-checkout check and a three-tab Mock browser walkthrough; those are historical results, not Milestone 06 verification. The dedicated reset command is limited to the marked `.demo` SQLite file and does not alter the normal development database.

The preceding serial-flow implementation had reported 108 backend tests and 22 frontend tests passing; those are historical results for the superseded Offer flow. On 2026-11-16 the current revision passed 139 backend tests, 32 frontend tests, frontend lint/build, `git diff --check`, and a tracked/candidate artifact scan covering 84 files. The automated suite covers repeatable old SQLite migration, isolated Demo reset, Mock setup/ready preflight, strict public Origin and Vite hostname parsing, startup failure for invalid public configuration, TLS/SNI WSS request construction, public Requester/Helper permissions and notification privacy, plus existing localhost and RFC1918 LAN behavior. Six independent headless Chrome contexts previously covered atomic edited-form confirmation; visibility and enabled response for Helpers with mismatched inventory, distant location or `unavailable` status; concurrent 200/409 claims; dismissal/restore; proposal rejection and acceptance; a G-building paid equipment-moving service completed by Kai without an item; and WebSocket polling recovery. These contexts ran on one host; three separate physical devices and a live Quick Tunnel across different networks have not been tested. No cloudflared process was started and no real Provider call was made.

## 3. Current Architecture

React/Vite uses HTTP for authoritative snapshots and WebSocket notifications for realtime updates. FastAPI services own SQLite data, publication, response validation, atomic claims, permissions and state. The Agent may propose only validated high-level actions; it cannot choose a Helper, confirm real-world capability or authorize a substitute. Classroom LAN and temporary public Origins are separate explicit allowlists. In public filming mode cloudflared targets only loopback Vite 5173; Vite proxies `/api` and `/ws` to loopback FastAPI 8000 without rewriting the browser Origin. DeepSeek is the configured primary model, local Ollama the fallback, and MockLLMProvider the offline test provider. Milestone 06 development, public filming and automated acceptance use Mock only. See [architecture](ARCHITECTURE.md).

## 4. Known Issues and Bugs

1. Demo role switching is not production authentication; real student data must not be used.
2. Real provider availability and Ollama model output can vary by machine; the development-machine smoke checks do not replace offline CI.
3. The in-memory realtime manager, single-process deadline checker and SQLite are suitable for the local demo, not a multi-worker deployment.
4. Static campus walking links and minutes are project estimates; building and footbridge access arrangements can change. They are neither live navigation nor a guarantee of access.
5. Quick Tunnel is a temporary testing service with a changing URL, no availability guarantee, a 200 in-flight request limit and no SSE support. Anyone holding the URL can access the fictional Demo while it is running; it is not authentication or a production deployment.

## 5. Next Decision

Run the remaining physical acceptance steps: first the classroom walkthrough on three separate devices using Alice, Erin, and Grace on the same hotspot or LAN; separately, with an already installed cloudflared, run the Mock-only public filming walkthrough using different networks, then stop the Tunnel, confirm the random URL is unavailable and reset the isolated Demo database. Review the uncommitted diff and record the user's acceptance decision. Preserve existing ignored Demo data during development. Do not automatically install cloudflared, and do not commit, push or merge until the user gives a separate instruction. Demo subscriptions remain fictional identity checks, not production authentication. Real-provider smoke testing requires separate approval with a stated scope and maximum call count.
