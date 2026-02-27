"""tools/orders.py — simple order action tools for the agent."""

import logging

logger = logging.getLogger(__name__)


def register(env, client, portfolio):
    """Register order management tools on the env."""

    def _apply_order_events(events: list[dict]) -> list[dict]:
        """Apply FIX order events to local portfolio and return trade fills."""
        fills: list[dict] = []
        for event in events:
            if event.get("type") != "execution_report":
                continue

            exec_type = event.get("exec_type")
            if exec_type == "TRADE":
                qty = int(event.get("last_qty") or 0)
                price = float(event.get("last_px") or 0.0)
                symbol = event.get("symbol", "")
                side = event.get("side", "")
                order_id = event.get("order_id", "")
                portfolio.record_fill(order_id, symbol, side, qty, price)
                fills.append({"symbol": symbol, "side": side, "qty": qty, "price": price})
            elif exec_type in ("CANCELED", "REJECTED", "EXPIRED"):
                portfolio.cancel_order(event.get("order_id", ""))
            elif exec_type == "REPLACED":
                original_id = event.get("orig_cl_ord_id", "")
                replacement_id = event.get("cl_ord_id", "")
                if original_id and replacement_id and original_id != replacement_id:
                    order_qty = event.get("order_qty")
                    if order_qty is None:
                        leaves_qty = event.get("leaves_qty")
                        cum_qty = event.get("cum_qty")
                        if isinstance(leaves_qty, (float, int)) and isinstance(cum_qty, (float, int)):
                            order_qty = leaves_qty + cum_qty
                    portfolio.apply_replacement(
                        original_id,
                        replacement_id,
                        qty=order_qty,
                        price=event.get("order_price"),
                        symbol=event.get("symbol") or None,
                        side=event.get("side") or None,
                    )
        return fills

    @env.tool()
    async def place_order(symbol: str, side: str, qty: int, price: float) -> dict:
        """Place a DAY LIMIT order."""
        side = side.strip().upper()
        if side not in ("BUY", "SELL"):
            return {"error": "side must be 'BUY' or 'SELL'"}
        if qty <= 0:
            return {"error": "qty must be a positive integer"}
        if price <= 0:
            return {"error": "price must be positive"}

        import uuid
        order_id = uuid.uuid4().hex[:8]

        err = portfolio.place_order(order_id, symbol, side, qty, float(price))
        if err:
            return {"error": err}

        try:
            client.place_order(
                symbol=symbol,
                side=side,
                qty=qty,
                price=float(price),
                order_id=order_id,
                order_type="LIMIT",
                time_in_force="DAY",
            )
        except Exception as exc:
            portfolio.cancel_order(order_id)
            return {"error": f"failed to send order: {exc}"}

        events = client.poll_order_events()
        fills = _apply_order_events(events)
        return {"order_id": order_id, "immediate_fills": len(fills)}

    @env.tool()
    async def replace_order(order_id: str, symbol: str, side: str, qty: int, price: float) -> dict:
        """Replace an active order with a new DAY LIMIT price/qty."""
        side = side.strip().upper()
        if side not in ("BUY", "SELL"):
            return {"error": "side must be 'BUY' or 'SELL'"}
        if qty <= 0:
            return {"error": "qty must be a positive integer"}
        if price <= 0:
            return {"error": "price must be positive"}

        try:
            replacement_id = client.replace_order(
                orig_order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=float(price),
                order_type="LIMIT",
                time_in_force="DAY",
            )
        except Exception as exc:
            return {"error": f"failed to send replace request: {exc}"}

        events = client.poll_order_events()
        fills = _apply_order_events(events)
        return {
            "replacement_order_id": replacement_id,
            "replaces": order_id,
            "immediate_fills": len(fills),
        }

    @env.tool()
    async def cancel_order(order_id: str, symbol: str, side: str) -> dict:
        """Cancel a pending order."""
        side = side.strip().upper()
        if side not in ("BUY", "SELL"):
            return {"error": "side must be 'BUY' or 'SELL'"}

        client.cancel_order(order_id, symbol, side)
        return {"cancelled": order_id}

    @env.tool()
    async def poll_fills() -> dict:
        """Fetch new fills and apply all pending order updates."""
        events = client.poll_order_events()
        fills = _apply_order_events(events)
        return {"fills": fills, "count": len(fills)}
