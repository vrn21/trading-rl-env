"""tasks/quant_tasks.py — hard quant trading scenarios."""

from grading import (
    EndFlatGrader,
    Grade,
    MaxDrawdownGrader,
    MaxInventoryGrader,
    PerSymbolProfitGrader,
    PnLGrader,
    ProfitFactorGrader,
    RoundTripGrader,
    SymbolsCoveredGrader,
    TradeActivityGrader,
)


def register(env, client, portfolio):
    """Register harder quant scenarios."""

    @env.scenario("maker-discipline")
    async def maker_discipline(
        symbol: str = "AMZ",
        initial_cash: float = 15_000.0,
        target_profit: float = 180.0,
        min_profitable_trips: int = 8,
        target_profit_factor: float = 1.6,
        max_inventory: float = 80.0,
        max_drawdown: float = 250.0,
    ):
        portfolio.reset(initial_cash=initial_cash)
        _ = yield f"""You are a trader on XETRA. Cash: ${initial_cash:,.0f}.
On {symbol}, make at least ${target_profit:,.0f} net profit.
Complete at least {min_profitable_trips} profitable round trips.
Keep peak open position at or below {max_inventory:.0f} shares.
Keep max drawdown at or below ${max_drawdown:,.0f}.
End with zero position."""

        grade = Grade.from_subscores([
            PnLGrader.grade(
                weight=0.18,
                portfolio=portfolio,
                initial_cash=initial_cash,
                target_profit=target_profit,
            ),
            RoundTripGrader.grade(
                weight=0.24,
                portfolio=portfolio,
                min_profitable_trips=min_profitable_trips,
            ),
            ProfitFactorGrader.grade(
                weight=0.22,
                portfolio=portfolio,
                target_profit_factor=target_profit_factor,
            ),
            MaxInventoryGrader.grade(
                weight=0.16,
                portfolio=portfolio,
                inventory_limit=max_inventory,
                per_symbol=True,
            ),
            MaxDrawdownGrader.grade(
                weight=0.10,
                portfolio=portfolio,
                initial_cash=initial_cash,
                max_drawdown=max_drawdown,
            ),
            EndFlatGrader.grade(
                weight=0.10,
                portfolio=portfolio,
            ),
        ])
        yield grade.score

    @env.scenario("underwater-unwind")
    async def underwater_unwind(
        initial_cash: float = 35_000.0,
        setup_symbol: str = "AMZ",
        setup_qty: int = 220,
        setup_avg_price: float = 103.0,
        target_profit: float = 250.0,
        target_profit_factor: float = 1.3,
        max_drawdown: float = 300.0,
        min_profitable_trips: int = 3,
    ):
        portfolio.reset(initial_cash=initial_cash)
        portfolio.record_fill("setup", setup_symbol, "BUY", setup_qty, setup_avg_price)

        _ = yield f"""You start with an open {setup_symbol} long: {setup_qty} shares at average {setup_avg_price:.2f}.
Recover this book and finish with at least ${target_profit:,.0f} net profit.
Keep max drawdown at or below ${max_drawdown:,.0f}.
Complete at least {min_profitable_trips} profitable round trips.
End with zero position."""

        grade = Grade.from_subscores([
            PnLGrader.grade(
                weight=0.25,
                portfolio=portfolio,
                initial_cash=initial_cash,
                target_profit=target_profit,
            ),
            EndFlatGrader.grade(
                weight=0.20,
                portfolio=portfolio,
            ),
            MaxDrawdownGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                initial_cash=initial_cash,
                max_drawdown=max_drawdown,
            ),
            ProfitFactorGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                target_profit_factor=target_profit_factor,
            ),
            RoundTripGrader.grade(
                weight=0.10,
                portfolio=portfolio,
                min_profitable_trips=min_profitable_trips,
            ),
            TradeActivityGrader.grade(
                weight=0.05,
                portfolio=portfolio,
            ),
        ])
        yield grade.score

    @env.scenario("balanced-cross-symbol")
    async def balanced_cross_symbol(
        initial_cash: float = 20_000.0,
        target_profit: float = 260.0,
        min_symbols: int = 3,
        required_profitable_symbols: int = 2,
        min_profit_per_symbol: float = 60.0,
        max_drawdown: float = 350.0,
    ):
        portfolio.reset(initial_cash=initial_cash)
        _ = yield f"""You are a trader on XETRA. Cash: ${initial_cash:,.0f}.
Make at least ${target_profit:,.0f} net profit.
Trade at least {min_symbols} symbols.
At least {required_profitable_symbols} symbols must each make ${min_profit_per_symbol:,.0f}+ realized profit.
Keep max drawdown at or below ${max_drawdown:,.0f}.
End with zero positions."""

        grade = Grade.from_subscores([
            PnLGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                initial_cash=initial_cash,
                target_profit=target_profit,
            ),
            SymbolsCoveredGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                min_symbols=min_symbols,
            ),
            PerSymbolProfitGrader.grade(
                weight=0.25,
                portfolio=portfolio,
                required_symbols=required_profitable_symbols,
                min_profit_per_symbol=min_profit_per_symbol,
            ),
            MaxDrawdownGrader.grade(
                weight=0.15,
                portfolio=portfolio,
                initial_cash=initial_cash,
                max_drawdown=max_drawdown,
            ),
            EndFlatGrader.grade(
                weight=0.10,
                portfolio=portfolio,
            ),
            ProfitFactorGrader.grade(
                weight=0.10,
                portfolio=portfolio,
                target_profit_factor=1.4,
            ),
        ])
        yield grade.score

    @env.scenario("small-capital-precision")
    async def small_capital_precision(
        initial_cash: float = 6_000.0,
        target_profit: float = 120.0,
        min_profitable_trips: int = 6,
        target_profit_factor: float = 1.8,
        max_drawdown: float = 120.0,
        max_inventory: float = 35.0,
    ):
        portfolio.reset(initial_cash=initial_cash)
        _ = yield f"""You are a trader on XETRA. Cash: ${initial_cash:,.0f}.
Make at least ${target_profit:,.0f} net profit.
Complete at least {min_profitable_trips} profitable round trips.
Keep profit factor at or above {target_profit_factor:.1f}.
Keep max drawdown at or below ${max_drawdown:,.0f}.
Keep peak position at or below {max_inventory:.0f} shares.
End with zero position."""

        grade = Grade.from_subscores([
            PnLGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                initial_cash=initial_cash,
                target_profit=target_profit,
            ),
            RoundTripGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                min_profitable_trips=min_profitable_trips,
            ),
            ProfitFactorGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                target_profit_factor=target_profit_factor,
            ),
            MaxDrawdownGrader.grade(
                weight=0.20,
                portfolio=portfolio,
                initial_cash=initial_cash,
                max_drawdown=max_drawdown,
            ),
            MaxInventoryGrader.grade(
                weight=0.10,
                portfolio=portfolio,
                inventory_limit=max_inventory,
                per_symbol=True,
            ),
            EndFlatGrader.grade(
                weight=0.10,
                portfolio=portfolio,
            ),
        ])
        yield grade.score

    @env.scenario("quant-gauntlet-hard")
    async def quant_gauntlet_hard(
        initial_cash: float = 25_000.0,
        target_profit: float = 450.0,
        min_symbols: int = 3,
        required_profitable_symbols: int = 3,
        min_profit_per_symbol: float = 70.0,
        min_profitable_trips: int = 10,
        target_profit_factor: float = 1.8,
        max_drawdown: float = 400.0,
        max_inventory: float = 120.0,
    ):
        portfolio.reset(initial_cash=initial_cash)
        _ = yield f"""You are a trader on XETRA. Cash: ${initial_cash:,.0f}.
Make at least ${target_profit:,.0f} net profit.
Trade at least {min_symbols} symbols.
Each of those {required_profitable_symbols} symbols must make at least ${min_profit_per_symbol:,.0f} realized profit.
Complete at least {min_profitable_trips} profitable round trips.
Keep profit factor at or above {target_profit_factor:.1f}.
Keep max drawdown at or below ${max_drawdown:,.0f}.
Keep peak position per symbol at or below {max_inventory:.0f} shares.
End with zero positions."""

        grade = Grade.from_subscores([
            PnLGrader.grade(
                weight=0.18,
                portfolio=portfolio,
                initial_cash=initial_cash,
                target_profit=target_profit,
            ),
            SymbolsCoveredGrader.grade(
                weight=0.12,
                portfolio=portfolio,
                min_symbols=min_symbols,
            ),
            PerSymbolProfitGrader.grade(
                weight=0.12,
                portfolio=portfolio,
                required_symbols=required_profitable_symbols,
                min_profit_per_symbol=min_profit_per_symbol,
            ),
            RoundTripGrader.grade(
                weight=0.14,
                portfolio=portfolio,
                min_profitable_trips=min_profitable_trips,
            ),
            ProfitFactorGrader.grade(
                weight=0.14,
                portfolio=portfolio,
                target_profit_factor=target_profit_factor,
            ),
            MaxDrawdownGrader.grade(
                weight=0.14,
                portfolio=portfolio,
                initial_cash=initial_cash,
                max_drawdown=max_drawdown,
            ),
            MaxInventoryGrader.grade(
                weight=0.08,
                portfolio=portfolio,
                inventory_limit=max_inventory,
                per_symbol=True,
            ),
            EndFlatGrader.grade(
                weight=0.08,
                portfolio=portfolio,
            ),
        ])
        yield grade.score
