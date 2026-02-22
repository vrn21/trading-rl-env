"""tools/orders.py — order action tools for the agent."""

import logging

logger = logging.getLogger(__name__)


def register(env, client, portfolio):
    """Register order management tools on the env."""

    @env.tool()
    async def place_order(symbol: str, side: str, qty: int, price: float) -> dict:
        """Place a LIMIT order on the simulated exchange.

        Args:
            symbol: Stock to trade (e.g. "AMZ", "MSF", "VOW")
            side:   "BUY" or "SELL"
            qty:    Number of shares (positive integer)
            price:  Limit price in USD (e.g. 150.50)

        Returns:
            {"order_id": str, "immediate_fills": int}

        Tip: Call poll_fills() after placing an order to check for execution.
        """
        if side not in ("BUY", "SELL"):
            return {"error": "side must be 'BUY' or 'SELL'"}
        if qty <= 0:
            return {"error": "qty must be a positive integer"}
        if price <= 0:
            return {"error": "price must be positive"}

        order_id = client.place_order(symbol, side, qty, price)
        fills = client.poll_fills()
        for f in fills:
            portfolio.record_fill(f["symbol"], f["side"], f["qty"], f["price"])
        return {"order_id": order_id, "immediate_fills": len(fills)}

    @env.tool()
    async def cancel_order(order_id: str, symbol: str, side: str) -> dict:
        """Cancel a pending limit order.

        Args:
            order_id: ID returned by place_order
            symbol:   Symbol of the original order
            side:     Original side ("BUY" or "SELL")

        Note: qty is NOT required for cancellation.
        """
        client.cancel_order(order_id, symbol, side)
        return {"cancelled": order_id}

    @env.tool()
    async def poll_fills() -> dict:
        """Check for any order executions (fills) since last call.

        Returns a list of fills. Each fill contains:
          symbol, side ("BUY"/"SELL"), qty, price

        Returns:
            {"fills": [...], "count": int}
        """
        fills = client.poll_fills()
        for f in fills:
            portfolio.record_fill(f["symbol"], f["side"], f["qty"], f["price"])
        return {"fills": fills, "count": len(fills)}
