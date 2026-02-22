"""Local test script for the trading RL environment.

Development workflow:
1. Start QuantReplay:  docker compose up -d
2. Start the env:      hud dev -w tasks -w grading --port 8765
3. Run this script:    python local_test.py
4. Edit tasks/ or grading/ → container auto-reloads → re-run
"""

import asyncio
import os

import hud
from hud import Environment
from hud.agents.claude import ClaudeAgent
from hud.settings import settings
from openai import AsyncOpenAI

# IMPORTANT: Do NOT import env from env.py here.
# Importing env.py would register tools locally (where backend clients aren't connected).
# A fresh Environment() routes all tool calls to the running container.
env = Environment("trading")

client = AsyncOpenAI(base_url="https://inference.hud.ai", api_key=settings.api_key)

DEV_URL = os.getenv("HUD_DEV_URL", "http://localhost:8765/mcp")
env.connect_url(DEV_URL)


async def test_tools_standalone() -> None:
    """Sanity check: call tools directly without a scenario or agent."""
    print("\n=== Test: Standalone Tools ===")

    async with env:
        tools = env.as_tools()
        print(f"Agent-visible tools: {[t.name for t in tools if not t.name.startswith('_')]}")

        print("\n--- list_symbols ---")
        print(await env.call_tool("list_symbols"))

        print("\n--- get_last_price (AMZ) ---")
        print(await env.call_tool("get_last_price", symbol="AMZ"))

        print("\n--- get_portfolio ---")
        print(await env.call_tool("get_portfolio"))


async def test_scenario() -> None:
    """Run the take-profit-basic scenario with a Claude agent."""
    print("\n=== Test: take-profit-basic ===")

    async with env:
        task = env("take-profit-basic")
        async with hud.eval(task, trace=True) as ctx:
            agent = ClaudeAgent.create(model="claude-sonnet-4-5")
            await agent.run(ctx, max_steps=50)


async def main() -> None:
    print("Trading RL Env — Local Test")
    print("=" * 50)
    print(f"Container: {DEV_URL}")
    print("Make sure the env is running:")
    print("  1. docker compose up -d")
    print("  2. hud dev -w tasks -w grading --port 8765")
    print("=" * 50)

    await test_tools_standalone()
    # Uncomment to run a full scenario with an agent:
    # await test_scenario()


if __name__ == "__main__":
    asyncio.run(main())
