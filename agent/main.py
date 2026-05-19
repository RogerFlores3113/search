from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.sse import EventSourceResponse, ServerSentEvent
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

from agent.events import DoneEvent, StateEvent
from agent import db as history_db
from agent.paths import get_secret_key
from agent.runner import run_agent


DISCLAIMER_COOKIE_NAME = "lba_disclaimer"
DISCLAIMER_COOKIE_VALUE = "1"
# 1 year persistence — disclaimer acceptance is a "did the user ever click
# the modal" record, not a session marker. Re-prompting every browser
# restart would train users to dismiss it without reading.
DISCLAIMER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _disclaimer_serializer() -> URLSafeSerializer:
    """Sign/verify the disclaimer cookie with the per-install secret.

    Lazy lookup of the secret key so tests that monkeypatch the data dir
    do not write to the real user_data_dir on import.
    """
    return URLSafeSerializer(get_secret_key(), salt="disclaimer")


def _disclaimer_accepted(request: Request) -> bool:
    """True iff the request carries a valid signed disclaimer cookie.

    Plain `?=1` without a valid signature is rejected so a stray cookie set
    by another local site/extension cannot pass the gate.
    """
    raw = request.cookies.get(DISCLAIMER_COOKIE_NAME)
    if not raw:
        return False
    try:
        value = _disclaimer_serializer().loads(raw)
    except BadSignature:
        return False
    return value == DISCLAIMER_COOKIE_VALUE


def _disclaimer_required_response() -> JSONResponse:
    return JSONResponse({"status": "disclaimer_required"}, status_code=403)


def _resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource, works in dev and frozen modes.

    Dev mode:   returns the relative path string unchanged
    Frozen app: returns str(Path(sys._MEIPASS) / relative)

    See: .planning/phases/04-distribution/04-RESEARCH.md Pitfall 5
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / relative)
    # Dev mode: resolve relative to the project root (parent of the agent
    # package) so callers that chdir away (e.g., pytest tmp_path fixtures)
    # still find bundled resources like agent/templates and agent/static.
    project_root = Path(__file__).resolve().parent.parent
    candidate = project_root / relative
    if candidate.exists():
        return str(candidate)
    return relative


templates = Jinja2Templates(directory=_resource_path("agent/templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan hook.

    On startup: initialise the runs DB table, then if app.state.pending_task is
    set, create an asyncio task for run_agent.
    On shutdown: cancel the task if still running.
    """
    await history_db.init_db()

    # Phase 12: Seed 4 named prompts on fresh install (no-op if 'prompts' key exists)
    from agent.settings import seed_prompts_if_absent, load_settings_json  # noqa: PLC0415
    seed_prompts_if_absent()
    # Live-patch config singleton so the first GET /api/settings returns seeds (Pitfall 5)
    _seeded = load_settings_json()
    from agent.config import config as _cfg  # noqa: PLC0415
    _cfg.prompts = _seeded.get("prompts", [])
    _cfg.active_prompt_id = _seeded.get("active_prompt_id", "generic")

    task_ref: Optional[asyncio.Task] = None
    pending = getattr(app.state, "pending_task", None)
    if pending:
        task_ref = asyncio.create_task(run_agent(pending))

    yield

    if task_ref is not None and not task_ref.done():
        task_ref.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(task_ref, return_exceptions=True), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # task outlived grace period; it will be garbage-collected


app = FastAPI(lifespan=lifespan)

# Default chrome_missing to False; set to True by __main__.py pre-flight check (DIST-02)
app.state.chrome_missing = False

# Mount static files with check_dir=False so startup does not crash when the
# agent/static directory has not yet been created (RESEARCH Anti-Patterns).
app.mount("/static", StaticFiles(directory=_resource_path("agent/static"), check_dir=False), name="static")

_active_task: Optional[asyncio.Task] = None
# Per-run SSE queues. Data queue (bounded, drop-on-overflow) carries
# screenshots and per-step updates; control queue (small, blocking puts)
# carries lifecycle events (state, model_info, summary, error, done) that
# the UI cannot recover from if dropped. `/stream` multiplexes both.
_active_queue: Optional[asyncio.Queue] = None
_active_control_queue: Optional[asyncio.Queue] = None
_active_agent = None                             # Agent ref for pause/stop (Plan 03)
# Serializes the busy-check + assignment in /run so two concurrent POSTs
# (double-clicked Run button, HTMX retry, two tabs) cannot both pass the
# `_active_task is None` check and both start a BrowserSession.
# Released the moment asyncio.create_task returns — the lock guards
# scheduling, NOT the duration of the run.
_start_lock = asyncio.Lock()


@app.get("/")
async def index(request: Request):
    """Render the HTMX+Alpine UI skeleton, or Chrome-missing page if Chrome not found.

    Passes `disclaimer_accepted` from the cookie so the modal only renders
    when truly unaccepted — eliminates the brief flash where the modal
    appears for a user who has already clicked through on a previous visit.
    """
    if getattr(request.app.state, "chrome_missing", False):
        return templates.TemplateResponse(request=request, name="no_chrome.html", context={})
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"disclaimer_accepted": _disclaimer_accepted(request)},
    )


@app.post("/accept-disclaimer")
async def accept_disclaimer_endpoint(request: Request):
    """Record the user's acceptance of the safety disclaimer.

    Sets a signed `httponly`, `SameSite=strict` cookie so neither another
    local site nor a cross-site form submission can pass the gate without
    the user clicking through the modal in this app.
    """
    signed = _disclaimer_serializer().dumps(DISCLAIMER_COOKIE_VALUE)
    response = JSONResponse({"status": "accepted"})
    response.set_cookie(
        DISCLAIMER_COOKIE_NAME,
        signed,
        httponly=True,
        samesite="strict",
        max_age=DISCLAIMER_COOKIE_MAX_AGE,
    )
    return response


@app.post("/run")
async def run_endpoint(request: Request, task: str = Form(..., max_length=2000)):
    """Accept a task string and start the agent as a fire-and-forget asyncio task.

    Accepts application/x-www-form-urlencoded (the HTMX default for form submissions).
    task is validated to a maximum of 2000 characters; FastAPI returns HTTP 422 if
    exceeded.

    Returns HTTP 409 if an agent session is already running to prevent multiple
    concurrent BrowserSession instances and interleaved JSONL writes.

    On accept: creates an asyncio.Queue, assigns it to _active_queue, starts the
    run_agent coroutine as an asyncio.Task with the queue wired in, and responds
    with HX-Trigger: streamStarted so the HTMX SSE container activates.
    """
    global _active_task, _active_queue, _active_control_queue
    if not _disclaimer_accepted(request):
        return _disclaimer_required_response()
    async with _start_lock:
        if _active_task is not None and not _active_task.done():
            return JSONResponse({"status": "busy"}, status_code=409)
        data_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        control_queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        _active_queue = data_queue
        _active_control_queue = control_queue
        _active_task = asyncio.create_task(
            run_agent(task, queue=data_queue, control_queue=control_queue)
        )
    return JSONResponse({"status": "started"}, headers={"HX-Trigger": "streamStarted"})


@app.post("/pause")
async def pause_endpoint(request: Request):
    """Toggle pause/resume on the active agent.

    If no agent is running, returns HTTP 400 with {"status": "no_active_run"}.
    If agent.state.paused is True, calls agent.resume() (sync — RESEARCH Pattern 5).
    Otherwise, calls agent.pause() (sync).
    Emits StateEvent("paused" or "running") to _active_queue.
    """
    global _active_agent, _active_queue, _active_control_queue
    if not _disclaimer_accepted(request):
        return _disclaimer_required_response()
    if _active_agent is None:
        return JSONResponse({"status": "no_active_run"}, status_code=400)
    # State transitions ride on the control queue (lifecycle), falling back
    # to the data queue for back-compat in test paths that wired only one.
    target = _active_control_queue if _active_control_queue is not None else _active_queue
    if _active_agent.state.paused:
        _active_agent.resume()
        if target is not None:
            target.put_nowait(StateEvent(state="running"))
        return JSONResponse({"status": "resumed"})
    else:
        _active_agent.pause()
        if target is not None:
            target.put_nowait(StateEvent(state="paused"))
        return JSONResponse({"status": "paused"})


@app.post("/stop")
async def stop_endpoint(request: Request):
    """Stop the active agent.

    If no agent is running, returns HTTP 400 with {"status": "no_active_run"}.
    Calls agent.stop() (sync) — the runner finally block handles status="stopped" in DB.
    """
    global _active_agent
    if not _disclaimer_accepted(request):
        return _disclaimer_required_response()
    if _active_agent is None:
        return JSONResponse({"status": "no_active_run"}, status_code=400)
    _active_agent.stop()
    return JSONResponse({"status": "stopped"})


@app.get("/runs")
async def runs_endpoint(request: Request):
    """Return the last 10 run records as an HTML fragment.

    All UI-facing aggregates (step_count, total_duration_s, total_cost_usd,
    model_name, provider) are columns on the runs row — computed once by
    `agent.runner.run_agent` when the run finishes. This endpoint is a
    straight SELECT; the LoRA-only `training/runs.jsonl` is not touched.
    """
    runs = await history_db.list_runs(limit=10)
    return templates.TemplateResponse(
        request=request, name="runs_fragment.html", context={"runs": runs}
    )


@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    """Return sanitized settings state — never plaintext keys, never encrypted blobs.

    Response shape (T-11-11 mitigation):
        provider, ollama_model, ollama_host, anthropic_model, openai_model,
        anthropic_key_set (bool), openai_key_set (bool),
        safety_defaults (sorted list), user_domains (list)
    """
    from agent.config import config, SAFETY_DEFAULTS
    from agent.settings import load_settings_json

    stored = load_settings_json()
    return JSONResponse({
        "provider": config.provider,
        "ollama_model": config.ollama_model,
        "ollama_host": config.ollama_host,
        "anthropic_model": config.anthropic_model,
        "openai_model": config.openai_model,
        "anthropic_key_set": bool(stored.get("anthropic_api_key_enc")),
        "openai_key_set": bool(stored.get("openai_api_key_enc")),
        "safety_defaults": sorted(SAFETY_DEFAULTS),
        "user_domains": list(config.user_domains),
        # Phase 12: prompt library fields — read from settings.json so fresh-install
        # seeding is reflected without requiring a config singleton live-patch first.
        # Content included; not secret (T-12-05). Safety guardrail constant not
        # included in API response (T-12-01 mitigation — see runner.py).
        "prompts": stored.get("prompts", list(config.prompts)),
        "active_prompt_id": stored.get("active_prompt_id", config.active_prompt_id),
    })


@app.get("/api/settings/ollama-models")
async def get_ollama_models() -> JSONResponse:
    """Proxy GET http://{ollama_host}/api/tags and return model name list.

    On any connection/timeout/JSON error returns {"models": [], "error": "unreachable"}
    so the settings UI panel remains functional even when Ollama is down (T-11-15).
    Uses async httpx (Pitfall 7 — not sync httpx.get).
    """
    from agent.config import config

    host = config.ollama_host.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            resp = await client.get(f"{host}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [
                m["name"]
                for m in data.get("models", [])
                if isinstance(m, dict) and "name" in m
            ]
            return JSONResponse({"models": models})
    except Exception:
        return JSONResponse({"models": [], "error": "unreachable"})


ALLOWED_PROVIDERS = {"ollama", "anthropic", "openai"}


@app.post("/api/settings")
async def post_settings(
    provider: str = Form(...),
    ollama_model: str = Form(""),
    ollama_host: str = Form(""),
    anthropic_model: str = Form(""),
    openai_model: str = Form(""),
    anthropic_key_action: str = Form("keep"),
    anthropic_key_value: str = Form(""),
    openai_key_action: str = Form("keep"),
    openai_key_value: str = Form(""),
    user_domains_json: str = Form("[]"),
    active_prompt_id: str = Form("generic"),
    prompts_json: str = Form("[]"),
) -> JSONResponse:
    """Save settings to settings.json and live-patch the config singleton.

    key_action ∈ {set, clear, keep} — prevents accidental key rotation on
    empty form submissions (Pitfall 4 / T-11-14 mitigation).

    user_domains filtered against SAFETY_DEFAULTS server-side — the UI also
    prevents overlap but the server is the trust boundary (T-11-13 mitigation).

    API key plaintext is never echoed in any response (T-11-12 mitigation).
    """
    try:
        import json as _json
        from agent.config import config, SAFETY_DEFAULTS
        from agent.settings import (
            load_settings_json,
            save_settings_json,
            encrypt_api_key,
            decrypt_api_key,
        )
        from pydantic import SecretStr

        # CR-02: Validate provider before any disk I/O
        if provider not in ALLOWED_PROVIDERS:
            return JSONResponse({"status": "error", "detail": "invalid provider"}, status_code=422)

        stored = load_settings_json()

        # --- Anthropic key handling (T-11-14) ---
        if anthropic_key_action == "set" and anthropic_key_value.strip():
            stored["anthropic_api_key_enc"] = encrypt_api_key(anthropic_key_value.strip())
        elif anthropic_key_action == "clear":
            stored.pop("anthropic_api_key_enc", None)
        # else: keep — no change

        # --- OpenAI key handling (T-11-14) ---
        if openai_key_action == "set" and openai_key_value.strip():
            stored["openai_api_key_enc"] = encrypt_api_key(openai_key_value.strip())
        elif openai_key_action == "clear":
            stored.pop("openai_api_key_enc", None)
        # else: keep — no change

        # --- user_domains validation (T-11-13) ---
        try:
            parsed = _json.loads(user_domains_json)
        except Exception:
            parsed = []
        cleaned: list[str] = []
        for d in parsed:
            if not isinstance(d, str):
                continue
            d = d.strip().lower()
            # Strip scheme and trailing slash (defensive — UI also does this)
            for scheme in ("https://", "http://"):
                if d.startswith(scheme):
                    d = d[len(scheme):]
            d = d.rstrip("/").strip()
            if not d:
                continue
            if d in SAFETY_DEFAULTS:
                continue  # filter SAFETY_DEFAULT overlap
            if d in cleaned:
                continue  # dedup
            cleaned.append(d)
        user_domains = cleaned

        # --- Phase 12: prompts validation (T-12-02 mitigation) ---
        try:
            parsed_prompts = _json.loads(prompts_json)
        except Exception:
            parsed_prompts = []
        # Keep only entries that are dicts with required keys (id, name, content)
        # is_seed is optional; non-conforming entries are dropped silently
        validated_prompts = [
            p for p in parsed_prompts
            if isinstance(p, dict) and "id" in p and "name" in p and "content" in p
        ]

        # --- Persist to settings.json ---
        stored["provider"] = provider
        stored["ollama_model"] = ollama_model or stored.get("ollama_model", config.ollama_model)
        stored["ollama_host"] = ollama_host or stored.get("ollama_host", config.ollama_host)
        stored["anthropic_model"] = anthropic_model or stored.get("anthropic_model", config.anthropic_model)
        stored["openai_model"] = openai_model or stored.get("openai_model", config.openai_model)
        stored["user_domains"] = user_domains
        stored["prompts"] = validated_prompts
        stored["active_prompt_id"] = active_prompt_id or "generic"
        save_settings_json(stored)

        # --- Live-patch config singleton (MUTABILITY_MODE: direct field assignment) ---
        config.provider = stored["provider"]
        config.ollama_model = stored["ollama_model"]
        config.ollama_host = stored["ollama_host"]
        config.anthropic_model = stored["anthropic_model"]
        config.openai_model = stored["openai_model"]
        config.user_domains = user_domains
        config.prompts = stored["prompts"]
        config.active_prompt_id = stored["active_prompt_id"]

        # Anthropic key live-patch
        anth_enc = stored.get("anthropic_api_key_enc")
        anth_plain = decrypt_api_key(anth_enc) if anth_enc else None
        config.anthropic_api_key = SecretStr(anth_plain) if anth_plain else None

        # OpenAI key live-patch
        oai_enc = stored.get("openai_api_key_enc")
        oai_plain = decrypt_api_key(oai_enc) if oai_enc else None
        config.openai_api_key = SecretStr(oai_plain) if oai_plain else None

        return JSONResponse({"status": "saved"})

    except Exception as e:
        # Never echo raw key values — generic error (T-11-12)
        return JSONResponse({"status": "error", "detail": str(e)[:200]}, status_code=500)


def _serialize_event(event: object) -> ServerSentEvent:
    return ServerSentEvent(
        raw_data=json.dumps(dataclasses.asdict(event)),
        event=event.type,
    )


@app.get("/stream", response_class=EventSourceResponse)
async def stream_events() -> AsyncIterable[ServerSentEvent]:
    """SSE endpoint that drains the active run queues until DoneEvent.

    Two-queue path (production): multiplexes the bounded data queue and the
    control queue via asyncio.wait. When DoneEvent arrives on the control
    queue, drains any remaining items off the data queue (the producers are
    quiesced by then — the screenshot loop is cancelled before run_agent's
    finally emits DoneEvent) and yields them before signaling done. This
    preserves the final frame and tail token updates the user expects to see.

    Single-queue path: back-compat for test code paths that wired one queue
    only — behaves exactly like the original loop.

    Idle path: no active run — yield a state:idle frame and close.

    Local queue refs are captured at connection time so a new run starting
    after the SSE connects does not cross-wire events (T-03-06).
    """
    global _active_queue, _active_control_queue
    if _active_queue is None:
        yield ServerSentEvent(raw_data='{"state":"idle"}', event="state")
        yield ServerSentEvent(raw_data="", event="done")
        return

    data_q = _active_queue
    ctrl_q = _active_control_queue

    if ctrl_q is None or ctrl_q is data_q:
        while True:
            event = await data_q.get()
            if isinstance(event, DoneEvent):
                yield ServerSentEvent(raw_data="", event="done")
                return
            yield _serialize_event(event)

    control_task = asyncio.create_task(ctrl_q.get())
    data_task = asyncio.create_task(data_q.get())
    pending: set[asyncio.Task] = {control_task, data_task}
    try:
        while True:
            completed, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            # Pre-scan: if DoneEvent is among the completed tasks, do NOT
            # re-arm any waiter — re-arming a queue.get() task on a queue
            # that already has items immediately consumes one of those
            # items into the new task's result, and that result is lost
            # when we cancel pending tasks on exit (the race that ate the
            # tail TokenEvent in test_stream_drains_data_queue_before_done).
            done_event_seen = any(
                isinstance(t.result(), DoneEvent) for t in completed
            )
            for task in completed:
                event = task.result()
                if isinstance(event, DoneEvent):
                    continue
                yield _serialize_event(event)
                if done_event_seen:
                    continue
                if task is control_task:
                    control_task = asyncio.create_task(ctrl_q.get())
                    pending.add(control_task)
                else:
                    data_task = asyncio.create_task(data_q.get())
                    pending.add(data_task)
            if done_event_seen:
                while True:
                    try:
                        tail = data_q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    yield _serialize_event(tail)
                yield ServerSentEvent(raw_data="", event="done")
                return
    finally:
        for t in pending:
            t.cancel()
