---
phase: 11
plan: "04"
subsystem: ui
tags: [settings, alpine, css, domain-safety, xss-guard]
dependency_graph:
  requires: [11-02, 11-03]
  provides: [settings-overlay-ui, gear-button, domain-two-tier-ui]
  affects: [agent/templates/index.html, agent/static/style.css]
tech_stack:
  added: []
  patterns: [alpine-x-for-xtext, alpine-x-show, fetch-post-formdata]
key_files:
  created: []
  modified:
    - agent/templates/index.html
    - agent/static/style.css
    - tests/unit/test_settings_phase11.py
decisions:
  - "Used &#x2699; HTML entity for gear icon (works in Jinja2 templates without escaping)"
  - "Used &#x1F512; HTML entity for lock icon to ensure clean HTML parsing"
  - "test_domain_list_two_tier_html checks innerHTML= (assignment) not innerHTML substring to avoid false-positive on hx-swap='innerHTML'"
  - "Gear button placed in flex div at top of .control-col with justify-content:flex-end per UI-SPEC"
metrics:
  duration: "~12 minutes"
  completed: "2026-05-18"
  tasks_completed: 2
  files_modified: 3
---

# Phase 11 Plan 04: Settings Overlay UI Summary

Settings overlay UI landed on top of the Plan 01–03 backend. Gear button opens a right-side panel with provider radios, API key inputs, Ollama model discovery, two-tier domain list, and Save Settings CTA — all wired via Alpine.js fetching the existing `/api/settings` routes.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add settings overlay markup + Alpine state/methods to index.html | 2646fcd | agent/templates/index.html, tests/unit/test_settings_phase11.py |
| 2 | Add settings overlay CSS to style.css | c330cd2 | agent/static/style.css |

## HTML Elements Added (index.html)

**Gear button** (in `.control-col` header):
- `<button type="button" class="btn-gear" aria-label="Open settings" aria-haspopup="dialog" @click="showSettings = true; loadSettings(); loadOllamaModels()">&#x2699;</button>`

**Settings overlay** (after disclaimer modal):
- `<div x-show="showSettings" role="dialog" aria-modal="true" aria-labelledby="settings-title" class="settings-overlay" @keydown.escape.window="showSettings = false">`
  - `.settings-header`: `<h2 id="settings-title">Settings</h2>` + Close button (`aria-label="Close settings"`)
  - `.provider-radio-group` fieldset with 3 radios: ollama, anthropic, openai (x-model=settingsProvider)
  - Ollama section (x-show=settingsProvider==='ollama'): model select (x-for ollamaModels), host input, unreachable warning
  - Anthropic section: type=password input + Clear button + read-only model span
  - OpenAI section: type=password input + Clear button + read-only model span
  - Domain Safety section (always visible): safetyDefaults x-for (🔒, no remove), userDomains x-for (✕ Remove ${d}), add-domain-row
  - `.settings-footer`: Save Settings button + `.save-confirm` span

## CSS Classes Added (style.css)

Section delimited by `/* Phase 11: Settings Overlay */`. Classes:
`.settings-overlay`, `.settings-panel`, `.settings-header`, `.settings-header h2`,
`.provider-radio-group`, `.provider-radio-group legend`, `.provider-radio-group label`,
`.settings-section`, `.settings-section h3`, `.settings-section p`,
`.settings-input`, `.settings-select`, `.settings-input::placeholder`,
`.settings-input:focus`, `.settings-select:focus`,
`.settings-model-readonly`, `.domain-list`, `.domain-row`,
`.domain-row--user button`, `.domain-row--user button:hover`,
`.add-domain-row`, `.add-domain-row .settings-input`,
`.settings-footer`, `.settings-footer .btn-primary`,
`.save-confirm`, `.btn-gear`, `.btn-gear:hover`, `.btn-gear:focus-visible`,
`.settings-warning`

No new CSS custom properties added to `:root` — all 15 existing tokens reused.

## Alpine Prop and Method Inventory

**Props added to agentUI():**
`showSettings` (bool, false), `settingsProvider` (str, "ollama"), `settingsOllamaModel` (str, ""),
`settingsOllamaHost` (str, "http://localhost:11434"), `ollamaModels` (array, []),
`ollamaUnreachable` (bool, false), `anthropicKeySet` (bool, false), `openaiKeySet` (bool, false),
`anthropicKeyAction` (str, "keep"), `openaiKeyAction` (str, "keep"),
`anthropicKeyValue` (str, ""), `openaiKeyValue` (str, ""),
`userDomains` (array, []), `safetyDefaults` (array, []), `newDomain` (str, ""), `savedMsg` (str, "")

**Methods added:** `openSettings()`, `loadSettings()`, `loadOllamaModels()`, `addDomain()`, `removeDomain(d)`, `saveSettings()`

## Test Inventory

All Phase 11 tests GREEN (25/25):

| Test | Status | Plan |
|------|--------|------|
| test_gear_button_present | GREEN | 04 (was RED) |
| test_settings_overlay_aria | GREEN | 04 (was RED) |
| test_domain_list_two_tier_html | GREEN | 04 (was RED) |
| test_no_innerhtml_phase11 | GREEN | 04 (new) |
| All 21 prior Phase 11 tests | GREEN | 01–03 |

Guard tests intact:
- `test_index_no_unsafe_html` (Phase 10 XSS guard): GREEN
- `test_no_cdn_scripts.py`: GREEN
- `test_events_phase10.py` (14 tests): GREEN
- Phase 8 pre-existing failures (3): unchanged

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] XSS guard test checked wrong substring**
- **Found during:** Task 1 verification
- **Issue:** Initial `test_domain_list_two_tier_html` checked `'innerHTML' not in stripped` but `hx-swap="innerHTML"` in the template is a legitimate HTMX attribute, causing false positive failure
- **Fix:** Changed assertion to `'innerHTML =' not in html` matching the existing `test_index_no_unsafe_html` pattern (checks JS assignment not attribute usage)
- **Files modified:** tests/unit/test_settings_phase11.py
- **Commit:** 2646fcd

## Known Stubs

None — all Alpine methods are fully wired to `/api/settings` endpoints built in Plan 03. Domain lists, model select, and save confirmation are fully functional.

## Threat Flags

No new security surface introduced beyond the threat model in the plan. T-11-18 (XSS via domain rendering) mitigated by strict `x-text`/`x-for` — no `innerHTML=` in index.html. T-11-19 (API key disclosure) mitigated by `type="password"` inputs never bound to server value.

## Self-Check: PASSED

- agent/templates/index.html: modified (gear button + overlay + Alpine props/methods)
- agent/static/style.css: modified (Phase 11 CSS section appended)
- tests/unit/test_settings_phase11.py: modified (3 RED tests flipped GREEN + 1 new)
- Commits 2646fcd and c330cd2 exist in git log
- 25/25 Phase 11 tests GREEN; 3 pre-existing Phase 8 failures only
