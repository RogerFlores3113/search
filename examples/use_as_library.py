"""Minimal example: run one browser task through the library.

Configure via environment, e.g.:
    LBA_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-... python examples/use_as_library.py "Find the title of example.com"
or with a local model:
    LBA_PROVIDER=ollama LBA_MODEL=qwen2.5vl:7b python examples/use_as_library.py
"""
import asyncio
import sys

from local_browser_agent import AgentConfig, BrowserAgent, CallbackSink


async def approve(request) -> bool:
    print(f"[approval] {request.action_name} on {request.element_label!r} at {request.url} -> denied")
    return False


async def main() -> int:
    task = sys.argv[1] if len(sys.argv) > 1 else "Open example.com and tell me the page heading."
    config = AgentConfig.from_env()  # reads LBA_* (plus ANTHROPIC_API_KEY / OPENAI_API_KEY)
    config.max_steps = 10
    agent = BrowserAgent(
        config,
        sinks=[CallbackSink(lambda e: print("event:", e.type) if e.type in ("state", "progress") else None)],
        approval=approve,
    )
    result = await agent.run(task, start_url="https://example.com")
    print(result.status, "-", result.final_result)
    print(f"{result.step_count} steps, {result.duration_s:.1f}s, cost={result.cost_usd}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
