"""tasks/take_profit.py — the take-profit trading scenario.

Mirrors tasks/basic.py from coding-template:
  setup → yield prompt → yield grade.score

The agent buys and sells a stock to reach a profit target.
Graded with two components:
  PnLGrader (0.8)           — how much profit vs target?
  TradeActivityGrader (0.2) — did the agent actually trade?
"""

from grading import Grade, PnLGrader, TradeActivityGrader


def register(env, client, portfolio):
    """Register trading scenarios on the env."""

    @env.scenario("take-profit-basic")
    async def take_profit_basic(
        symbol: str = "AMZ",
        initial_cash: float = 15_000.0,
        target_profit: float = 300.0,
    ):
        """Buy and sell {symbol} to make ${target_profit} profit."""

        # ── Setup ─────────────────────────────────────────────────────────
        portfolio.reset(initial_cash=initial_cash)

        # ── Prompt ────────────────────────────────────────────────────────
        _ = yield f"""You are a trading agent on a simulated stock exchange (XETRA).

Account: ${initial_cash:,.0f} virtual cash
Goal:    Make at least ${target_profit:,.0f} in net profit
Stock:   {symbol} — one of [AMZ, MSF, NFC, VODI, VOW]

How to trade:
  1. Place a BUY order near the current market price
  2. Wait for it to fill (call poll_fills)
  3. Place a SELL order above your buy price
  4. Check your P&L with get_portfolio

Tools available:
  list_symbols()                          → see all tradeable stocks
  place_order(symbol, side, qty, price)   → submit BUY or SELL limit order
  poll_fills()                            → check if orders were executed
  cancel_order(order_id, symbol, side)    → cancel a pending order
  get_last_price(symbol)                  → last price from your fills
  get_portfolio()                         → cash, positions, net profit

Price discovery: You won't know the exact price until your first order fills.
Start with a BUY order and adjust if it doesn't fill. The market has random
order generation running so the book is active.

Final score = 0.8 × (profit / target) + 0.2 × (trade activity)
"""

        # ── Grade ─────────────────────────────────────────────────────────
        grade = Grade.from_subscores([
            PnLGrader.grade(
                weight=0.8,
                portfolio=portfolio,
                initial_cash=initial_cash,
                target_profit=target_profit,
            ),
            TradeActivityGrader.grade(
                weight=0.2,
                portfolio=portfolio,
            ),
        ])
        yield grade.score
