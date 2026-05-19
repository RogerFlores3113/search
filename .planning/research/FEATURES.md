# Feature Research

**Domain:** Local AI browser agent — settings panel, prompt library, task presets, prompt engineering, auth audit (v0.3.0)
**Researched:** 2026-05-18
**Confidence:** HIGH for settings/prompt patterns and auth posture; HIGH for prompt engineering guidance; MEDIUM for WSL-specific cross-filesystem behavior

---

## v0.3.0 New Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Persistent API key storage | Users refuse to re-enter keys on every launch | LOW | Store in sqlite settings table — NOT pickle (see Anti-Features). Mask input, show/hide toggle. Never in .env checked to git. |
| Ollama model auto-discovery | Users don't know model IDs; manual text entry is error-prone | LOW | HTTP GET `http://localhost:11434/api/tags` or subprocess `ollama list`. Populate dropdown; include a refresh button. |
| Provider + model selector UI | Users switch Ollama/Anthropic/OpenAI frequently | LOW | Provider dropdown gates which model list is shown. Anthropic/OpenAI use known-model enum or text input. |
| Domain exclusion list with safety defaults | Users expect agent to never touch banking, payments, gov, medical without explicit intent | MEDIUM | Pre-fill non-editable defaults (e.g., chase.com, paypal.com, irs.gov, medlineplus.gov). User-extensible list persisted in sqlite. Enforcement at CDP level already wired in v0.1.0 — settings panel is the management UI only. |
| Settings persistence across launches | Users expect configuration to survive restarts | LOW | sqlite (aiosqlite) already in stack. A `settings` table with one row per key (key/value JSON) is sufficient. |
| Active system prompt indicator | Users need to know which prompt is active before running | LOW | Active prompt name/ID stored in settings table. Display name near task input box. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Prompt library with named saves | Iterate on prompts without losing prior versions; enables systematic improvement over time | LOW | CRUD on a `prompt_library` sqlite table: id, name, body, created_at, is_active. |
| A/B testing support for prompts | Compare two system prompt variants across task runs without rebuilding infrastructure | LOW | Store prompt_id on each run record in `run_history`. Post-hoc comparison via run history table — no runtime switching needed. |
| Task presets (apartment / job / candidate) | Pre-fills task + selects domain-tuned system prompt; dramatically reduces first-use friction | MEDIUM | Three preset buttons on main UI. Each carries a task template string and a linked prompt_id from the library. Task field remains editable before run. |
| Deep per-domain system prompts | Generic prompts produce mediocre results on structured search tasks; domain-tuned prompts reliably extract the right fields and handle site-specific navigation patterns | HIGH (research/writing effort) | 4 curated prompts shipped as seed data: generic, apartment, job, candidate. See Prompt Engineering section below for content guidance. |
| Prompt library pre-seeded with curated defaults | An empty library at first launch is a UX dead end; users see value immediately | LOW | Ship 4 prompts in db init migration: generic assistant, apartment search, job search, candidate/lead search. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Using Windows Chrome profile/cookies from WSL | Seems to enable logged-in agent sessions | Chrome 115+ policy blocks automating the active default profile; concurrent access corrupts the profile data; security risk (see Auth Audit section) | Agent runs a fresh isolated Chrome instance. Credential sharing is a v2 feature requiring explicit secure storage design and UX. |
| Pickle for settings serialization | Python-native, trivially easy | CVE-level vulnerability: pickle deserialization executes arbitrary code; browser-use/web-ui was exploited this way (Kudelski Security Research, patched in that project's v1.7). The attack works on localhost-only tools via iframe injection from malicious websites. | JSON blob column in aiosqlite settings table. No serialization beyond json.dumps/loads. |
| Auto-saving API keys to .env file | Seems developer-friendly | .env files are accidentally committed to git; ambiguous ownership when the app is a bundled .app/.exe | sqlite settings table with restrictive file permissions (0600 on Unix). |
| Cloud sync for prompt library | Multi-device convenience | Contradicts local-first security posture; prompt library + API keys = sensitive data; adds infrastructure complexity | Export/import as JSON file — implement as v2 if users request it. |
| Real-time prompt switching mid-task | Power users want this | browser-use agent context (including the system prompt) is fixed at task initialization. Mid-run mutation causes unpredictable behavior. | Stop task, change active prompt, start new task. Clean lifecycle. |
| Per-domain separate API key sets | "I want to use Anthropic for apartment search and OpenAI for job search" | Multiplies settings surface area; users don't actually think this way | One active provider/model per session is sufficient for v0.3.0. |

---

## Feature Dependencies

```
Prompt Library (CRUD)
    └──required by──> Active Prompt Selection (settings stores active_prompt_id)
    └──required by──> Task Presets (each preset links to a prompt_id)
    └──required by──> A/B Testing (run_history stores prompt_id per run)

Settings Panel (data layer first)
    └──required by──> Ollama Model Auto-discovery (settings stores selected model)
    └──required by──> API Key Management (settings stores provider keys)
    └──required by──> Domain Exclusion List UI (settings stores exclusion set)
    └──required by──> Active Prompt Selection (settings stores active_prompt_id)

Domain Exclusion List
    └──enhances──> existing CDP blocklist guardrail (already wired in v0.1.0)

Task Presets
    └──requires──> Prompt Library (preset links to a prompt_id — build library first)
    └──enhances──> existing task input box (pre-fills it; no new input component needed)

Deep Prompt Engineering (writing/content work)
    └──required by──> Task Presets (presets are only as good as their bundled prompts)
    └──feeds──> Prompt Library seed data (4 curated prompts in db init)
```

### Dependency Notes

- **Build settings data layer before settings UI.** The aiosqlite `settings` table and `prompt_library` table must exist before any UI panel can read or write. Implement the data layer (models + migrations) in the first phase of settings work.
- **Task Presets require Prompt Library entries.** A preset is a task template string + a foreign key to a prompt_id. The prompt must exist in the library before the preset can be seeded. Ship prompts first, then wire preset buttons.
- **Domain Exclusion enforces via existing CDP blocklist.** The settings panel adds a management UI for an already-working enforcement mechanism. No new CDP integration is needed — only a way to read/write the exclusion set from settings and pass it to the existing runner.

---

## MVP for v0.3.0

### Launch With

- [x] Settings panel: API key inputs (masked, show/hide toggle), provider + model selector with Ollama auto-discovery, domain exclusion list with pre-filled non-editable safety defaults + user-extensible entries
- [x] Prompt library: CRUD (save, name, list, set active, delete), seed database with 4 curated prompts on first init
- [x] Task presets: 3 preset buttons (apartment, job, candidate) — pre-fills task input and selects linked system prompt
- [x] Deep system prompts: 1 generic + 3 domain-specific prompts (see content in Prompt Engineering section)
- [x] Auth posture documented: fresh-profile-only policy enforced by default, findings written up

### Defer to v1.x

- [ ] Prompt version history / diff view — trigger: users ask "what changed" between prompt iterations
- [ ] A/B testing comparison UI — trigger: users doing manual comparison in run history first
- [ ] Export/import prompt library as JSON — trigger: multi-machine users

### Defer to v2+

- [ ] Authenticated sessions (saved logins via OS keychain) — requires dedicated security design
- [ ] Preset marketplace / community prompt sharing — requires identity and trust model

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Settings panel (API keys + model selector) | HIGH | LOW | P1 |
| Ollama model auto-discovery | HIGH | LOW | P1 |
| Prompt library (CRUD + active selection) | HIGH | LOW | P1 |
| Domain exclusion list | HIGH | LOW | P1 |
| Prompt library seed data (4 curated prompts) | HIGH | LOW | P1 |
| Task presets (3 presets) | HIGH | MEDIUM | P1 |
| Deep domain system prompts (writing effort) | HIGH | MEDIUM | P1 |
| A/B testing linkage (run history prompt_id) | MEDIUM | LOW | P2 |
| Prompt version history / diff | MEDIUM | MEDIUM | P2 |
| Export/import prompt library JSON | LOW | LOW | P3 |

---

## Prompt Engineering: What Makes Agentic Browser Prompts Effective

### Core Principles (HIGH confidence — multiple independent sources)

**1. Use `extend_system_message`, not `override_system_message`.**
browser-use's default system prompt encodes its DOM extraction strategy, element interaction model, and error recovery logic. Overriding it means re-implementing all of that from scratch. Extending appends domain guidance on top of the working foundation. Per browser-use official docs: "Only use extend_system_message or override_system_message when you intentionally want to customize default behavior for your task." Recommendation: always extend, never override, for domain customization.

**2. Establish environmental boundaries first — before task instructions.**
Tell the agent what world it is operating in before giving it goals. For this app: it has a real Chrome instance, can see screenshots, can click/type/scroll/navigate, but cannot access the filesystem, cannot submit payment forms, and must not enter credentials. (Source: PromptHub guide; Treasure AI agent system prompt template)

**3. Use numbered steps to sequence operations.**
LLMs default to parallel reasoning. Numbered lists enforce chronological order and prevent the agent from trying to extract data before navigating to the page. From PromptHub: "Numbered lists establish chronological order... set checkpoints to verify completion before advancing, reducing hallucinations." This is especially important for search tasks with a defined multi-site workflow.

**4. Define the output schema explicitly.**
Agents default to prose descriptions. For search tasks (apartments, jobs, candidates), specify exact field names: list them as a bullet or as a JSON schema example. This prevents the agent from writing a paragraph instead of a structured record. If a field is unavailable, specify it should be `null` — not omitted, not inferred.

**5. Include explicit stop conditions.**
Agents without termination criteria will loop on failures or keep paginating indefinitely. State: "Stop after collecting N results" and "If a CAPTCHA appears, stop navigation on that site and move to the next." This is critical for multi-site search tasks where each site has pagination.

**6. Add time/cost awareness cues.**
LLMs lack temporal perception. Include: "Each browser action takes real time. Take the most direct path to the target content. Do not visit pages unlikely to contain listings." This reduces unnecessary navigation hops and keeps run costs predictable.

**7. Specify safety rails at the action level, not just the structural level.**
The CDP blocklist handles site-level blocking. The system prompt must reinforce at action level: "Never click Apply/Submit/Pay buttons. Never enter credentials. Never create accounts. Collect and return data only." Redundancy across layers is appropriate for safety-critical constraints.

**8. Declare the output location and format explicitly.**
End the prompt with: "Return all collected data as a JSON array. Each item must be a flat object with consistent field names. Write a one-sentence summary after the JSON of what was found and any sites that were blocked."

### Generic System Prompt (seed content for `extend_system_message`)

```
You are a research assistant that uses a real Chrome browser to collect information from websites.

RULES (follow strictly):
1. Never submit forms, click payment buttons, or enter any credentials or personal information.
2. Never create accounts, sign up for services, or agree to terms of service on any site.
3. If you encounter a CAPTCHA or a mandatory login wall, stop navigation on that site and move on to the next.
4. Collect data only. Do not interact with a page beyond what is needed to view and extract information.
5. Each browser action takes real time. Take the most direct path to the target content.
6. Stop and return results once you have collected the requested number of items or exhausted available pages.

OUTPUT FORMAT:
Return all collected data as a JSON array. Each item must be a flat object with consistent field names.
If a field is not available on the page, use null — do not omit the field.
After the JSON array, write one sentence summarizing what you found and noting any sites that were blocked or failed.
```

### Apartment Search System Prompt (addition to extend_system_message)

```
APARTMENT SEARCH GUIDANCE:
Target sites in this order: Craigslist (local housing/apartments section), Zillow, Apartments.com, Zumper, Trulia.
On Craigslist: navigate to the local housing section. Apply price range and bedroom count filters if filter controls are visible without clicking individual listings.
On Zillow/Apartments.com: use the search bar with the location from the task. Apply price and bedroom filters from the filter UI.
Extract per listing: title, price_per_month, bedrooms, bathrooms, square_feet (null if not shown), neighborhood, address (null if not shown), listing_url, date_posted, source_site.
Ignore sponsored or "featured" placements that show inflated or outlier prices.
If pagination exists, follow Next Page up to 3 pages per site before moving on.
Stop after collecting 20 listings total or exhausting all target sites.
Do not open individual listing detail pages unless the list view does not show price, bedrooms, or address.
```

### Job Search System Prompt (addition to extend_system_message)

```
JOB SEARCH GUIDANCE:
Target sites in this order: LinkedIn Jobs, Indeed, Glassdoor, Wellfound (for startups). Add company career pages if the task names a specific company.
On LinkedIn: use the Jobs tab search. Use the list/preview panel — do not open individual job pages unless the preview does not show required fields.
On Indeed: use the search bar. Filters for date posted and job type are in the left sidebar.
Extract per listing: job_title, company_name, location, is_remote (true/false), salary_range (null if not shown), date_posted, job_url, source_site, employment_type (full-time/contract/part-time, null if not stated).
Do not apply, send connection requests, message recruiters, or follow companies.
If "Show more results" or pagination exists, use it up to 3 times per site.
Stop after collecting 20 listings or exhausting all target sites.
```

### Candidate / Lead Search System Prompt (addition to extend_system_message)

```
CANDIDATE AND LEAD SEARCH GUIDANCE:
Target sites as specified in the task. Common sources: LinkedIn People search, company About/Team pages, GitHub (for technical roles), Wellfound.
On LinkedIn: use People search with the filters provided in the task (title, location, company). Collect from the search results list view — do not open individual profiles.
Extract per result: full_name, current_title, current_company, location, profile_url, source_site, contact_info (email or phone number only if displayed publicly on the page without clicking through — null otherwise).
Do not send connection requests, messages, InMails, or follow anyone.
Do not navigate to profile pages that require a login to view — collect only what is visible without authentication.
Stop after collecting the number of candidates specified in the task. If no number is given, stop at 20.
```

---

## Auth Audit: WSL Chrome Credential Posture

### How the App Launches Chrome (current v0.2.0 behavior)

The app uses `playwright.chromium.launch(channel="chrome")` — this launches the user's installed Google Chrome binary with a **fresh, empty, temporary profile** (Playwright's default behavior when no `userDataDir` is provided). It does NOT point to any existing Chrome profile on the machine.

### What This Means in WSL2

When running in WSL2, the app locates the Windows Chrome binary (e.g., via `/mnt/c/Program Files/Google/Chrome/Application/chrome.exe`) and launches it with a temporary profile. Because no `userDataDir` is passed, the agent profile starts completely empty.

**The agent has NO access to:**
- The Windows user's saved passwords or credentials
- The Windows user's cookies (including saved login sessions)
- The Windows user's browsing history or localStorage
- The Windows user's Chrome extensions

**This is correct behavior and the desired security posture for v0.3.0.**

### Chrome Policy Constraint (HIGH confidence — official Playwright docs)

Even if the code explicitly pointed `userDataDir` at the Windows default Chrome profile (`/mnt/c/Users/<user>/AppData/Local/Google/Chrome/User Data/`), Chrome 115+ policy **blocks automation of the active default user profile**. Pages fail to load or the browser exits immediately. This is a Google-enforced restriction, not a Playwright bug or WSL limitation.

Additionally, Chrome cannot open a profile that is already open in another window — concurrent access to the same `userDataDir` is not supported. Attempting this would corrupt the Windows user's profile.

### WSL2 Sandboxing Note (MEDIUM confidence — WSL kernel limitation)

Playwright running in WSL2 that launches a Linux Chromium binary requires `--no-sandbox` because WSL2 does not fully support Linux namespaces (missing kernel capabilities for the Chromium security sandbox). This is a known WSL2 limitation. When launching the Windows `chrome.exe` binary from WSL2 (via `/mnt/c/...`), the Chrome sandbox runs under Windows (not WSL2 Linux), so this specific issue does not apply to the Windows Chrome launch path.

The current app uses cdp-use to drive Chrome — the sandbox behavior should be confirmed against the actual `launch()` call args in runner.py, but no code change is indicated by the audit.

### Security Posture Summary

| Scenario | Credential Access | Assessment |
|----------|------------------|------------|
| Fresh temporary profile (current behavior) | None — profile is empty | Correct. Agent starts clean every run. No user data at risk. |
| Pointing at Windows default Chrome profile | Blocked by Chrome 115+ policy | Even if attempted, Chrome refuses to launch. |
| Pointing at non-default Windows profile via /mnt/c/ | Technically possible — Chrome will open it | Dangerous: concurrent access with active Chrome corrupts the profile. Do NOT implement. |
| launchPersistentContext with agent-dedicated dir | Persists cookies between agent runs only | Valid v2 option for session reuse — requires explicit UX design for credential scope and revocation. |

### Recommendation

Document current posture as "isolated by design." No code change needed for v0.3.0. The AUTH-01 deliverable is a written finding in PROJECT.md or a SECURITY.md note, not a code change.

Authenticated sessions (login as a specific user, maintain cookies across runs) are a v2 feature. They require: (1) explicit user authorization flow, (2) storage of session tokens via OS keychain (not sqlite plaintext), (3) clear scope and revocation UX. Do not shortcut this as a settings panel option in v0.3.0.

---

## Competitor Feature Analysis

| Feature | browser-use/web-ui | OpenHands / Devin-style | Our Approach |
|---------|------------------|--------------------------|--------------|
| Settings persistence | Pickle files (CVE — patched in v1.7 of that project) | .env / YAML config files | sqlite JSON blob — safe, no pickle, survives app restarts |
| API key storage | Previously in pickle-serialized config (exposed in CVE) | .env file (git risk) | sqlite settings table, masked input, 0600 file permissions |
| Model selector | Gradio dropdown, re-init required on change | Config file edit + restart | Dropdown in settings panel, takes effect on next run |
| Prompt management | Single system prompt textarea, no persistence | Project-level prompt files in repo | Named prompt library with active selection, CRUD, preset linkage |
| Task presets | None (general purpose only) | Task templates in some tools | 3 domain-tuned presets with linked system prompts |
| Auth posture | No documented posture; web-ui had RCE via browser with disabled security flags | Varies | Fresh isolated profile, documented posture, v2 credential design |

---

## Sources

- [browser-use System Prompt docs](https://docs.browser-use.com/customize/system-prompt) — extend_system_message vs override_system_message, official guidance
- [browser-use/awesome-prompts GitHub](https://github.com/browser-use/awesome-prompts) — prompt categories; job search, data extraction, multi-step workflow patterns
- [PromptHub: Prompt Engineering for AI Agents](https://www.prompthub.us/blog/prompt-engineering-for-ai-agents) — numbered step sequencing, holistic planning, checkpoint verification
- [Treasure AI: Agent System Prompt Best Practices](https://docs.treasure.ai/products/customer-data-platform/ai-agent-foundry/ai-agent/system-prompt-best-practices) — structure, task flow, output format directives, error handling, character limits
- [Kudelski Security: RCE on browser-use/web-ui](https://kudelskisecurity.com/research/getting-rce-on-browser-use-web-ui-ai-agent-instances) — pickle CVE, API key exposure vector, remediation (use JSON, environment variables)
- [Playwright Authentication Docs](https://playwright.dev/docs/auth) — profile isolation, userDataDir limitations, Chrome 115+ default-profile restriction
- [Playwright BrowserType API](https://playwright.dev/docs/api/class-browsertype) — launchPersistentContext, userDataDir behavior
- [Playwright MCP on WSL2 sandboxing](https://markaicode.com/playwright-mcp-wsl-chromium-sandboxing-fixes/) — WSL2 kernel namespace limitations for Chromium sandbox
- [Setproduct: App Settings UI Design](https://www.setproduct.com/blog/settings-ui-design) — two-level settings, grouping, toggle UX, progressive disclosure
- [Hashicorp Helios: Masked Input pattern](https://helios.hashicorp.design/components/form/masked-input) — API key show/hide toggle, default-masked design
- [Agentic AI Prompt Engineering (UBTI)](https://ubtiinc.com/agentic-ai-prompt-engineering-key-concepts-techniques-and-best-practices/) — environmental constraints, modular action sequencing, safety guidelines
- [Building Browser Agents: Architecture and Security (arXiv 2511.19477)](https://arxiv.org/html/2511.19477v1) — indirect prompt injection vulnerability in browser agents; safety rail placement guidance

---

## Historical Research: v0.2.0 Foundations (for reference)

*The following research was produced for the v0.2.0 milestone and is preserved here for continuity. It covers observability UI, model transparency, fine-tuning improvement estimates, and training data quality signals.*

**Domain:** Local AI browser agent — observability, model transparency, training data pipeline
**Researched:** 2026-05-16
**Overall confidence:** HIGH (observability UX), MEDIUM-HIGH (fine-tuning improvements), HIGH (training data quality signals)

### Agent Observability UI — Table Stakes (v0.2.0)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-step elapsed time | Users need to know if the agent is stuck or slow | Low | Wall-clock seconds per step, not just total elapsed |
| Total run duration | Cost/performance evaluation after the run | Low | Already tracked client-side; needs server-side precision |
| Token count per step | Users paying per-token API costs must know what they spent | Low | Provider callbacks expose this; format as `in: X / out: Y` |
| Cumulative cost display | Running dollar total during the run | Low | Derived from token counts + provider pricing table |
| Step counter with max | "Step 4 of 25" — users need progress horizon | Low | Already in UI (`stepNum / maxSteps`); needs SSE push from server |
| Current action label | "Clicking: Submit button" not "Step 4: navigate" | Low | browser-use action result includes element target and action type |
| Status badge: running/paused/complete/error | Already present in v0.1.0 | Done | Already implemented |
| Pause/stop controls | User must be able to interrupt | Done | Already implemented |
| Final summary / error message | What the agent accomplished or why it failed | Done | Already implemented |
| Screenshot viewport | Live view of what the browser sees | Done | Already implemented; needs lag fix (SCR-01/02) |

### Agent Observability UI — Differentiators (v0.2.0)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| LLM thought text (chain-of-thought) | Surfaces why the agent chose an action — builds trust, aids debugging | Medium | Claude extended thinking returns `thinking_delta` SSE events; Qwen2.5-VL returns `<think>` tag in text; needs normalization layer |
| Action type color badges | Visual scan of what kind of steps ran (navigate vs click vs type vs scroll) | Low | CSS classes per action type; `action_type` already in browser-use result |
| Per-step token breakdown | Breakdown inside narration row: "in: 1,240 / out: 89" | Low | Requires token count forwarded from LLM callback to SSE event |
| Cost-per-step inline | "$0.008" next to each step | Low | Derived from token count + model pricing constant |
| Expandable run history with cost/duration | See per-run totals without re-running | Medium | Requires enriched DB schema: tokens_total, cost_usd, duration_ms |
| Near real-time screenshot streaming | Screenshot updates every ~500ms during action execution, not after | Medium | Background asyncio capture loop with SSE push; main current lag issue |

### Expected Fine-tuning Improvements (v0.2.0 research)

| Approach | Baseline | After SFT | Improvement | Citation |
|----------|----------|-----------|-------------|---------|
| Qwen-2.5-3B with SFT | 6.1% | 20.0% | +14pp (+230%) | WebAgent-R1, EMNLP 2025 |
| Llama-3.1-8B with SFT | 8.5% | 20.6% | +12pp (+142%) | WebAgent-R1, EMNLP 2025 |
| ScribeAgent fine-tuned on 250-domain dataset | unspecified | 51.3% TSR on WebArena | +7.3pp over prior SOTA | ScribeAgent, CMU 2024 |

### v0.2.0 Sources

- [WebAgent-R1 (EMNLP 2025, arXiv 2505.16421)](https://arxiv.org/abs/2505.16421)
- [ScribeAgent: Fine-Tuning for Web Navigation (CMU ML Blog, 2024)](https://blog.ml.cmu.edu/2024/12/06/scribeagent-fine-tuning-open-source-llms-for-enhanced-web-navigation/)
- [Scaling Web Agent Training (arXiv 2602.12544)](https://arxiv.org/html/2602.12544)
- [LangSmith Observability Platform](https://www.langchain.com/langsmith/observability)
- [Anthropic Extended Thinking docs](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
- [Unsloth Vision Fine-tuning docs](https://unsloth.ai/docs/basics/vision-fine-tuning)

---
*Feature research for: local-browser-agent v0.3.0 — settings panel, prompt library, task presets, prompt engineering, auth audit*
*Researched: 2026-05-18*
