# """
# The prompt in this specific task is not the best. I dont want the prompts to be so voerly specified. so when anyone trie to write their own tasks, make sure that the prompt is really short and to the point, dont talk much about the market or the tools, let the agent find its way on its own.

# tasks/take_profit.py — take-profit trading scenario.

# Ground truth from QuantReplay demo data (db/market-simulator/sample-data/demo/xetra/):
#   AMZ: mid_price=100, bid=98, ask=102 (EUR)
#        qty_min=1, qty_max=2000
#        random_orders_rate=3/sec (active market liquidity)
#        order_on_startup=true (random orders start immediately)
#   Venue: cancel_on_disconnect=false (orders survive reconnect)
#          no market phases (always Open/continuous trading)
#          timezone=UTC

# Price discovery strategy:
#   1. Call market_data_snapshot() to read current bid/ask
#   2. Use a small probe order only if needed (snapshot pending/rejected)
#   3. Sell above your average buy price to realize profit

# Grading (two components):
#   PnLGrader (0.8)           — realized profit vs target
#   TradeActivityGrader (0.2) — was there at least a round-trip trade?
# """

# from grading import Grade, PnLGrader, TradeActivityGrader


# def register(env, client, portfolio):
#     """Register trading scenarios on the env."""

#     @env.scenario("take-profit-basic")
#     async def take_profit_basic(
#         symbol: str = "AMZ",
#         initial_cash: float = 15_000.0,
#         target_profit: float = 200.0,
#     ):
#         """Buy and sell {symbol} to earn ${target_profit} in net profit.

#         AMZ trades near 100 EUR with a bid/ask spread of ~98/102.
#         Random orders fire at 3/sec providing ample liquidity.
#         You will only be given very limited amount of turns to complete the task [under 30 turns] So make sure that you actually get profit as fast as possible
#         """

#         # ── Setup ─────────────────────────────────────────────────────────
#         portfolio.reset(initial_cash=initial_cash)

#         # ── Prompt ────────────────────────────────────────────────────────
#         _ = yield f"""You are a trading agent on the XETRA simulated stock exchange.

# ACCOUNT
#   Cash:    ${initial_cash:,.0f} (virtual EUR)
#   Goal:    Earn at least ${target_profit:,.0f} net profit

# STOCK: {symbol}
#   Price:   ~100 EUR (use market_data_snapshot() for bid/ask)
#   Qty:     1–2000 shares per order
#   Market:  Active (random orders fire at ~3/sec)

# PRICE DISCOVERY (important — read this)
#   1. Call market_data_snapshot("{symbol}", "TOP")
#      → read best_bid / best_ask
#   2. If needed, place a small BUY probe and call poll_fills()
#      → read actual fill price with get_last_price("{symbol}")
#   3. Place a SELL order above your buy price to capture profit

# HOW TO PROFIT
#   Strategy: buy low, sell high.
#   Example: buy 100 shares at ~102, sell at ~104 → $200 profit
#   The market generates random liquidity so prices drift gradually.
#   After your buy fills, wait briefly then submit a sell above your avg buy price.

# TOOLS
#   list_symbols()                          → see all tradeable stocks (AMZ, MSF, NFC, VODI, VOW)
#   get_listing_rules(symbol)               → min/max qty and price tick size
#   market_data_snapshot(symbol, depth)     → current top-of-book or full snapshot
#   place_order(symbol, side, qty, price)   → submit a BUY or SELL limit order
#   replace_order(order_id, symbol, side, qty, price) → update price/qty of a live order
#   poll_fills()                            → check if your orders executed (call after placing orders)
#   cancel_order(order_id, symbol, side)    → cancel a pending unfilled order
#   get_last_price(symbol)                  → your last fill price for a symbol
#   get_portfolio()                         → current cash, positions, and net profit

# SCORING
#   Score = 0.8 × clamp(profit / {target_profit}, 0, 1)
#         + 0.2 × trade_activity
#   where trade_activity = 0 (no trades), 0.5 (one side), 1.0 (buy+sell)

# Start by checking market_data_snapshot(), then execute buy-low / sell-higher.
# """

#         # ── Grade ─────────────────────────────────────────────────────────
#         grade = Grade.from_subscores([
#             PnLGrader.grade(
#                 weight=0.8,
#                 portfolio=portfolio,
#                 initial_cash=initial_cash,
#                 target_profit=target_profit,
#             ),
#             TradeActivityGrader.grade(
#                 weight=0.2,
#                 portfolio=portfolio,
#             ),
#         ])
#         yield grade.score
