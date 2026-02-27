"""tools/portfolio.py — portfolio observation tool."""

import logging

logger = logging.getLogger(__name__)


def register(env, client, portfolio):
    """Register the portfolio tool on the env."""

    @env.tool()
    async def get_portfolio() -> dict:
        """Get your current cash balance, open positions, and net profit.

        Returns:
            {
              "cash": float,
              "net_profit": float,
              "positions": {"AMZ": {"qty": 100, "avg_price": 150.0}},
              "total_fills": int
            }
        """
        return portfolio.to_dict()
