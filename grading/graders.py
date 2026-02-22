"""grading/graders.py — PnLGrader and TradeActivityGrader.

Two graders used together in every trading scenario:
  PnLGrader           (weight=0.8) — did the agent make profit?
  TradeActivityGrader (weight=0.2) — did the agent trade at all?

Combined score = PnLGrader*0.8 + TradeActivityGrader*0.2

Rationale for two graders:
  - An agent that does nothing scores 0 on both.
  - An agent that buys then sells (round trip) but loses money gets 0.2.
  - An agent that hits the full profit target gets 1.0.
  This gradient helps RL training distinguish "did nothing" from "tried".
"""

from typing import Any

from .spec import Grader


class PnLGrader(Grader):
    """Grades profit-and-loss vs a target.

    Score = clamp(actual_profit / target_profit, 0.0, 1.0)
    """

    name = "PnLGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        initial_cash: float,
        target_profit: float,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        profit = portfolio.net_profit()
        score = max(0.0, min(1.0, profit / target_profit)) if target_profit > 0 else 0.0
        return score, {
            "actual_profit":  round(profit, 2),
            "target_profit":  target_profit,
            "final_cash":     round(portfolio.cash, 2),
        }


class TradeActivityGrader(Grader):
    """Grades whether the agent actually traded.

    Score:
      0.0 = no fills at all (agent did nothing)
      0.5 = at least 1 fill (placed an order that executed)
      1.0 = at least 1 BUY and 1 SELL (completed a round trip)
    """

    name = "TradeActivityGrader"

    @classmethod
    def compute_score(cls, portfolio: Any, **kwargs) -> tuple[float, dict[str, Any]]:
        fills = portfolio.fills
        buys  = sum(1 for f in fills if f["side"] == "BUY")
        sells = sum(1 for f in fills if f["side"] == "SELL")

        if buys > 0 and sells > 0:
            score = 1.0
        elif len(fills) > 0:
            score = 0.5
        else:
            score = 0.0

        return score, {"total_fills": len(fills), "buy_fills": buys, "sell_fills": sells}
