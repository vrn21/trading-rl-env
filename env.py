"""Trading RL Environment — MCP server entry point.

Started from hud-blank. Extended to add:
  tools/    : market data + order tools (what the agent can call)
  grading/  : PnLGrader + Grade/SubGrade/Grader base class
  tasks/    : scenario definitions (setup → prompt → grade)
  backend/  : QuantReplayClient (REST + FIX) + Portfolio

This file only wires the pieces together — no business logic here.
Mirrors coding-template/env.py in structure.
"""

import logging
import sys

from hud import Environment

from backend import QuantReplayClient, Portfolio
from tools import market, orders, portfolio
from tasks import basic_tasks, quant_tasks

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(levelname)s] %(name)s | %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
env = Environment("trading")
_client = QuantReplayClient()
_portfolio = Portfolio()


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@env.initialize
async def initialize() -> None:
    if not await _client.health_check():
        raise RuntimeError("QuantReplay not reachable on port 9050. Is it running?")
    _client.connect()
    logger.info("Trading env ready.")


@env.shutdown
async def shutdown() -> None:
    _client.disconnect()
    await _client.close()


# ── Register tools ────────────────────────────────────────────────────────────
market.register(env, _client, _portfolio)
orders.register(env, _client, _portfolio)
portfolio.register(env, _client, _portfolio)

# ── Register scenarios ────────────────────────────────────────────────────────

basic_tasks.register(env, _client, _portfolio)
quant_tasks.register(env, _client, _portfolio)


if __name__ == "__main__":
    env.run(transport="stdio")
