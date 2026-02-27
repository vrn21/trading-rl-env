"""tools/market.py — simple market observation tools for the agent."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def register(env, client, portfolio):
    """Register market tools on the env."""

    @env.tool()
    async def list_symbols() -> dict:
        """List all tradeable symbols."""
        return {"symbols": await client.get_listings()}

    @env.tool()
    async def get_listing_rules(symbol: str) -> dict:
        """Get quantity/price constraints for a symbol."""
        try:
            listing = await client.get_listing(symbol)
        except Exception as exc:
            return {"error": f"failed to load listing {symbol}: {exc}"}

        return {
            "symbol": listing.get("symbol", symbol),
            "venue_id": listing.get("venueId"),
            "constraints": {
                "qty_minimum": listing.get("qtyMinimum"),
                "qty_maximum": listing.get("qtyMaximum"),
                "qty_multiple": listing.get("qtyMultiple"),
                "price_tick_size": listing.get("priceTickSize"),
            },
        }

    @env.tool()
    async def market_data_snapshot(symbol: str, depth: str = "TOP") -> dict:
        """Fetch a simple market snapshot from FIX.

        Args:
            symbol: listing symbol (e.g. "AMZ")
            depth: "TOP" or "FULL"

        Returns best bid/ask, last trade, and raw entries.
        """
        depth = depth.strip().upper()
        if depth not in ("TOP", "FULL"):
            return {"error": "depth must be 'TOP' or 'FULL'"}

        try:
            req_id = client.market_data_snapshot(
                symbol=symbol,
                depth=depth,
                entry_types="BID,OFFER,TRADE",
            )
        except Exception as exc:
            return {"error": str(exc)}

        events = client.poll_market_data_events()
        if not any(event.get("request_id") == req_id for event in events):
            await asyncio.sleep(0.05)
            events.extend(client.poll_market_data_events())

        matched = [event for event in events if event.get("request_id") == req_id]
        if not matched:
            return {
                "request_id": req_id,
                "symbol": symbol,
                "status": "pending",
                "message": "snapshot not received yet; call again",
            }

        reject = next((event for event in matched if event.get("type") == "market_data_reject"), None)
        if reject:
            return {
                "request_id": req_id,
                "symbol": symbol,
                "error": reject.get("reason") or reject.get("text") or "market data request rejected",
                "details": reject,
            }

        snapshot = next(
            (event for event in matched if event.get("type") in ("market_data_snapshot", "market_data_update")),
            None,
        )
        if snapshot is None:
            return {
                "request_id": req_id,
                "symbol": symbol,
                "status": "pending",
                "message": "snapshot event not available yet; call again",
            }

        entries = snapshot.get("entries", [])
        bids = [entry for entry in entries if entry.get("entry_type") == "BID" and isinstance(entry.get("price"), (float, int))]
        offers = [entry for entry in entries if entry.get("entry_type") == "OFFER" and isinstance(entry.get("price"), (float, int))]
        trades = [entry for entry in entries if entry.get("entry_type") == "TRADE" and isinstance(entry.get("price"), (float, int))]

        best_bid = max(bids, key=lambda entry: float(entry["price"])) if bids else None
        best_ask = min(offers, key=lambda entry: float(entry["price"])) if offers else None
        last_trade = trades[-1] if trades else None

        return {
            "request_id": req_id,
            "symbol": symbol,
            "depth": depth,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "last_trade": last_trade,
            "entry_count": len(entries),
            "entries": entries,
        }

    @env.tool()
    async def get_last_price(symbol: str) -> dict:
        """Get last fill price from this agent's own trade history."""
        return {"symbol": symbol, "last_price": portfolio.last_price(symbol)}
