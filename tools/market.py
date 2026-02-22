"""tools/market.py — market observation tools for the agent.

NOTE: QuantReplay has no REST orderbook endpoint.
Price discovery uses the last fill price from portfolio history.
For a fresh market with no fills yet, list_symbols() tells the agent
what's available; the agent must place a small probe order to discover price.
"""

import logging

logger = logging.getLogger(__name__)


def register(env, client, portfolio):
    """Register market data tools on the env."""

    @env.tool()
    async def list_symbols() -> dict:
        """List all tradeable symbols on the simulated exchange.

        Returns:
            {"symbols": ["AMZ", "MSF", "NFC", "VODI", "VOW"]}
        """
        return {"symbols": await client.get_listings()}

    @env.tool()
    async def get_last_price(symbol: str) -> dict:
        """Get the last traded price for a symbol from your fill history.

        Returns None if no fills exist yet for this symbol.
        Use place_order() to discover the market price by submitting a
        limit order and checking if it fills.

        Args:
            symbol: e.g. "AMZ", "MSF", "VOW"

        Returns:
            {"symbol": str, "last_price": float | None}
        """
        price = portfolio.last_price(symbol)
        return {"symbol": symbol, "last_price": price}
