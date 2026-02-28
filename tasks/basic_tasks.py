"""tasks/basic_tasks.py — beginner-friendly trading scenarios."""

from grading import Grade, PnLGrader, TradeActivityGrader


def register(env, client, portfolio):
    """Register basic scenarios."""

    @env.scenario("take-profit-basic")
    async def take_profit_basic(
        symbol: str = "AMZ",
        initial_cash: float = 15_000.0,
        target_profit: float = 200.0,
    ):
        portfolio.reset(initial_cash=initial_cash)
        _ = yield f"""You are a trader on XETRA. Starting cash: ${initial_cash:,.0f}.

Goal: make at least ${target_profit:,.0f} net profit trading {symbol}.

Use the provided tools to place/cancel orders, poll fills, and track your portfolio.
Your score is based on your portfolio state (not explanations)."""

        grade = Grade.from_subscores(
            [
                PnLGrader.grade(
                    weight=0.80,
                    portfolio=portfolio,
                    initial_cash=initial_cash,
                    target_profit=target_profit,
                ),
                TradeActivityGrader.grade(
                    weight=0.20,
                    portfolio=portfolio,
                ),
            ]
        )
        yield grade.score

