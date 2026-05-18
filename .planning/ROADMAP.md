# Roadmap: local-browser-agent

## Milestones

- ✅ **v0.1.0 MVP** — Phases 1-4 (shipped 2026-05-16)
- ✅ **v0.2.0 Foundations** — Phases 5-9.1 (shipped 2026-05-18)
- 📋 **v0.3.0 Visual + Distribution** — Phases 10+ (planned)

## Phases

<details>
<summary>✅ v0.1.0 MVP (Phases 1-4) — SHIPPED 2026-05-16</summary>

- [x] Phase 1: Scaffold + Core Loop PoC (3/3 plans) — completed 2026-05-13
- [x] Phase 2: Multi-Provider + Guardrails (2/2 plans) — completed 2026-05-15
- [x] Phase 3: Full Web UI (3/3 plans) — completed 2026-05-16
- [x] Phase 4: Distribution (2/2 plans) — completed 2026-05-16

See archive: `.planning/milestones/v0.1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v0.2.0 Foundations (Phases 5-9.1) — SHIPPED 2026-05-18</summary>

- [x] Phase 5: Token Counting + Timing (2/2 plans) — completed 2026-05-17
- [x] Phase 6: Model Transparency (2/2 plans) — completed 2026-05-17
- [x] Phase 7: Screenshot Streaming (2/2 plans) — completed 2026-05-17
- [x] Phase 8: Training Data Enrichment (2/2 plans) — completed 2026-05-18
- [x] Phase 9: Frontend Polish (2/2 plans) — completed 2026-05-18
- [x] Phase 9.1: Close gap PERF-01 — wire step_duration_ms (2/2 plans) — completed 2026-05-18

See archive: `.planning/milestones/v0.2.0-ROADMAP.md`

</details>

### 📋 v0.3.0 Visual + Distribution (Planned)

**Milestone Goal:** Fix visual rendering gaps from v0.2.0, ship Windows distribution, and validate the full app with a manual smoke test before adding presets.

- [ ] **Phase 10: Visual UI Refactor** — Confirm and fix all v0.2.0 UI rendering gaps (per-step duration, token ticker, action badges, thought blocks, run history expansion); address CR-01 timer placement in runner.py
- [ ] **Phase 11: Windows Distribution** — .exe build via PyInstaller on Windows CI runner; validate launch + Chrome detection on Windows 10/11
- [ ] **Phase 12: Manual Smoke Test + Notarization** — Human-verified 5-scenario test run; full Apple notarization for Gatekeeper auto-pass

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Scaffold + Core Loop PoC | v0.1.0 | 3/3 | Complete | 2026-05-13 |
| 2. Multi-Provider + Guardrails | v0.1.0 | 2/2 | Complete | 2026-05-15 |
| 3. Full Web UI | v0.1.0 | 3/3 | Complete | 2026-05-16 |
| 4. Distribution | v0.1.0 | 2/2 | Complete | 2026-05-16 |
| 5. Token Counting + Timing | v0.2.0 | 2/2 | Complete | 2026-05-17 |
| 6. Model Transparency | v0.2.0 | 2/2 | Complete | 2026-05-17 |
| 7. Screenshot Streaming | v0.2.0 | 2/2 | Complete | 2026-05-17 |
| 8. Training Data Enrichment | v0.2.0 | 2/2 | Complete | 2026-05-18 |
| 9. Frontend Polish | v0.2.0 | 2/2 | Complete | 2026-05-18 |
| 9.1. Close gap PERF-01 | v0.2.0 | 2/2 | Complete | 2026-05-18 |
| 10. Visual UI Refactor | v0.3.0 | 0/? | Not started | — |
| 11. Windows Distribution | v0.3.0 | 0/? | Not started | — |
| 12. Manual Smoke Test + Notarization | v0.3.0 | 0/? | Not started | — |
