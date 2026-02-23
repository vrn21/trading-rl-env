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

        import uuid
        order_id = uuid.uuid4().hex[:8]

        # ── Budget enforcement ─────────────────────────────────────────────────
        err = portfolio.place_order(order_id, symbol, side, qty, price)
        if err:
            return {"error": err}
        # ── End budget enforcement ─────────────────────────────────────────────

        client.place_order(symbol, side, qty, price, order_id=order_id)
        
        fills = client.poll_fills()
        real_fills = []
        for f in fills:
            if f.get("type") == "CANCEL":
                portfolio.cancel_order(f["order_id"])
            else:
                portfolio.record_fill(f.get("order_id", ""), f["symbol"], f["side"], f["qty"], f["price"])
                real_fills.append({"symbol": f["symbol"], "side": f["side"], "qty": f["qty"], "price": f["price"]})
        return {"order_id": order_id, "immediate_fills": len(real_fills)}

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
        real_fills = []
        for f in fills:
            if f.get("type") == "CANCEL":
                portfolio.cancel_order(f["order_id"])
            else:
                portfolio.record_fill(f.get("order_id", ""), f["symbol"], f["side"], f["qty"], f["price"])
                real_fills.append({"symbol": f["symbol"], "side": f["side"], "qty": f["qty"], "price": f["price"]})
        return {"fills": real_fills, "count": len(real_fills)}
