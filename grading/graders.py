"""grading/graders.py — trading task graders."""

from collections import defaultdict, deque
from math import isfinite
from typing import Any

from .spec import Grader


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _iter_fifo_matches(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FIFO-match buy lots against sell fills per symbol."""
    buy_queues: dict[str, deque[list[float]]] = defaultdict(deque)
    matches: list[dict[str, Any]] = []

    for fill in fills:
        symbol = str(fill.get("symbol", "")).strip()
        side = str(fill.get("side", "")).upper()
        qty = float(fill.get("qty", 0) or 0)
        price = float(fill.get("price", 0) or 0)

        if not symbol or qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            buy_queues[symbol].append([qty, price])
            continue

        if side != "SELL":
            continue

        remaining = qty
        queue = buy_queues[symbol]
        while remaining > 1e-12 and queue:
            lot_qty, lot_price = queue[0]
            matched_qty = min(remaining, lot_qty)
            pnl = (price - lot_price) * matched_qty
            matches.append(
                {
                    "symbol": symbol,
                    "qty": matched_qty,
                    "buy_price": lot_price,
                    "sell_price": price,
                    "pnl": pnl,
                }
            )

            remaining -= matched_qty
            lot_qty -= matched_qty
            if lot_qty <= 1e-12:
                queue.popleft()
            else:
                queue[0][0] = lot_qty

    return matches


def _realized_pnl_per_symbol(fills: list[dict[str, Any]]) -> dict[str, float]:
    realized: dict[str, float] = defaultdict(float)
    for match in _iter_fifo_matches(fills):
        realized[match["symbol"]] += float(match["pnl"])
    return dict(realized)


def _max_drawdown_from_fills(fills: list[dict[str, Any]], initial_cash: float) -> float:
    cash = float(initial_cash)
    positions: dict[str, float] = defaultdict(float)
    last_prices: dict[str, float] = {}

    peak_equity = cash
    worst_drawdown = 0.0

    for fill in fills:
        symbol = str(fill.get("symbol", "")).strip()
        side = str(fill.get("side", "")).upper()
        qty = float(fill.get("qty", 0) or 0)
        price = float(fill.get("price", 0) or 0)

        if not symbol or qty <= 0 or price <= 0:
            continue

        last_prices[symbol] = price
        if side == "BUY":
            cash -= qty * price
            positions[symbol] += qty
        elif side == "SELL":
            cash += qty * price
            positions[symbol] -= qty
        else:
            continue

        equity = cash
        for pos_symbol, pos_qty in positions.items():
            if abs(pos_qty) <= 1e-12:
                continue
            equity += pos_qty * last_prices.get(pos_symbol, 0.0)

        peak_equity = max(peak_equity, equity)
        worst_drawdown = max(worst_drawdown, peak_equity - equity)

    return worst_drawdown


class PnLGrader(Grader):
    name = "PnLGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        initial_cash: float,
        target_profit: float,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        profit = float(portfolio.net_profit())
        score = _clamp(profit / target_profit) if target_profit > 0 else 0.0
        return score, {
            "actual_profit": round(profit, 2),
            "target_profit": float(target_profit),
            "final_cash": round(float(portfolio.cash), 2),
        }


class TradeActivityGrader(Grader):
    name = "TradeActivityGrader"

    @classmethod
    def compute_score(cls, portfolio: Any, **kwargs) -> tuple[float, dict[str, Any]]:
        fills = portfolio.fills
        buys = sum(1 for fill in fills if str(fill.get("side", "")).upper() == "BUY")
        sells = sum(1 for fill in fills if str(fill.get("side", "")).upper() == "SELL")

        if buys > 0 and sells > 0:
            score = 1.0
        elif fills:
            score = 0.5
        else:
            score = 0.0

        return score, {"total_fills": len(fills), "buy_fills": buys, "sell_fills": sells}


class EndFlatGrader(Grader):
    name = "EndFlatGrader"

    @classmethod
    def compute_score(cls, portfolio: Any, **kwargs) -> tuple[float, dict[str, Any]]:
        open_qty = 0.0
        positions = getattr(portfolio, "positions", {}) or {}
        for symbol, pos in positions.items():
            qty = float((pos or {}).get("qty", 0) or 0)
            if abs(qty) > 1e-12:
                open_qty += abs(qty)

        score = 1.0 if open_qty <= 1e-12 else 0.0
        return score, {"open_qty": round(open_qty, 6)}


class MaxDrawdownGrader(Grader):
    name = "MaxDrawdownGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        initial_cash: float,
        max_drawdown: float,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        worst_dd = _max_drawdown_from_fills(list(portfolio.fills), initial_cash=float(initial_cash))
        if max_drawdown <= 0:
            score = 1.0 if worst_dd <= 0 else 0.0
        elif worst_dd <= max_drawdown:
            score = 1.0
        else:
            score = _clamp(1.0 - ((worst_dd - max_drawdown) / max_drawdown))

        return score, {
            "max_drawdown": round(worst_dd, 2),
            "threshold": float(max_drawdown),
        }


class RoundTripGrader(Grader):
    name = "RoundTripGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        min_profitable_trips: int = 1,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        matches = _iter_fifo_matches(list(portfolio.fills))
        profitable = sum(1 for match in matches if float(match["pnl"]) > 0)
        total = len(matches)
        realized = sum(float(match["pnl"]) for match in matches)

        if min_profitable_trips <= 0:
            score = 1.0 if profitable > 0 else 0.0
        else:
            score = _clamp(profitable / float(min_profitable_trips))

        return score, {
            "profitable_trips": int(profitable),
            "total_trips": int(total),
            "min_required": int(min_profitable_trips),
            "realized_pnl": round(realized, 2),
        }


class SymbolsCoveredGrader(Grader):
    name = "SymbolsCoveredGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        min_symbols: int = 1,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        symbols = sorted(
            {
                str(fill.get("symbol", "")).strip()
                for fill in portfolio.fills
                if str(fill.get("symbol", "")).strip()
            }
        )
        count = len(symbols)
        if min_symbols <= 0:
            score = 1.0
        else:
            score = _clamp(count / float(min_symbols))
        return score, {"symbols_traded": symbols, "count": count, "min_required": int(min_symbols)}


class ProfitFactorGrader(Grader):
    name = "ProfitFactorGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        target_profit_factor: float = 1.5,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        matches = _iter_fifo_matches(list(portfolio.fills))
        pnls = [float(match["pnl"]) for match in matches]
        gross_profit = sum(pnl for pnl in pnls if pnl > 0)
        gross_loss = sum(-pnl for pnl in pnls if pnl < 0)

        if gross_profit <= 0:
            profit_factor = 0.0
        elif gross_loss <= 1e-12:
            profit_factor = float("inf")
        else:
            profit_factor = gross_profit / gross_loss

        if target_profit_factor <= 1.0:
            score = 1.0 if profit_factor > 1.0 else 0.0
        elif not isfinite(profit_factor):
            score = 1.0
        else:
            score = _clamp((profit_factor - 1.0) / (target_profit_factor - 1.0))

        return score, {
            "profit_factor": "inf" if not isfinite(profit_factor) else round(profit_factor, 4),
            "target_profit_factor": float(target_profit_factor),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "matched_trades": len(matches),
        }


class PerSymbolProfitGrader(Grader):
    name = "PerSymbolProfitGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        required_symbols: int = 1,
        min_profit_per_symbol: float = 0.0,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        pnl_by_symbol = _realized_pnl_per_symbol(list(portfolio.fills))
        profitable_symbols = [
            symbol
            for symbol, pnl in pnl_by_symbol.items()
            if pnl >= float(min_profit_per_symbol)
        ]

        if required_symbols <= 0:
            score = 1.0
        else:
            score = _clamp(len(profitable_symbols) / float(required_symbols))

        return score, {
            "required_symbols": int(required_symbols),
            "min_profit_per_symbol": float(min_profit_per_symbol),
            "profitable_symbols": sorted(profitable_symbols),
            "count_profitable_symbols": len(profitable_symbols),
            "realized_pnl_by_symbol": {k: round(v, 2) for k, v in sorted(pnl_by_symbol.items())},
        }


class MaxInventoryGrader(Grader):
    name = "MaxInventoryGrader"

    @classmethod
    def compute_score(
        cls,
        portfolio: Any,
        inventory_limit: float,
        per_symbol: bool = True,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        positions: dict[str, float] = defaultdict(float)
        peak_by_symbol: dict[str, float] = defaultdict(float)
        peak_total_inventory = 0.0

        for fill in portfolio.fills:
            symbol = str(fill.get("symbol", "")).strip()
            side = str(fill.get("side", "")).upper()
            qty = float(fill.get("qty", 0) or 0)
            if not symbol or qty <= 0:
                continue

            if side == "BUY":
                positions[symbol] += qty
            elif side == "SELL":
                positions[symbol] -= qty
            else:
                continue

            peak_by_symbol[symbol] = max(peak_by_symbol[symbol], abs(positions[symbol]))
            peak_total_inventory = max(peak_total_inventory, sum(abs(v) for v in positions.values()))

        peak_inventory = (
            max(peak_by_symbol.values(), default=0.0)
            if per_symbol
            else peak_total_inventory
        )

        if inventory_limit <= 0:
            score = 1.0 if peak_inventory <= 0 else 0.0
        elif peak_inventory <= inventory_limit:
            score = 1.0
        else:
            score = _clamp(1.0 - ((peak_inventory - inventory_limit) / inventory_limit))

        return score, {
            "inventory_limit": float(inventory_limit),
            "peak_inventory": round(peak_inventory, 4),
            "per_symbol": bool(per_symbol),
            "peak_inventory_by_symbol": {k: round(v, 4) for k, v in sorted(peak_by_symbol.items())},
            "peak_total_inventory": round(peak_total_inventory, 4),
        }


class StepBudgetGrader(Grader):
    name = "StepBudgetGrader"

    @classmethod
    def compute_score(
        cls,
        steps_used: int,
        step_budget: int,
        **kwargs,
    ) -> tuple[float, dict[str, Any]]:
        used = int(steps_used)
        budget = int(step_budget)

        if budget <= 0:
            score = 1.0 if used <= 0 else 0.0
        elif used <= budget:
            score = 1.0
        else:
            score = _clamp(1.0 - ((used - budget) / float(budget)))

        return score, {"steps_used": used, "step_budget": budget}
