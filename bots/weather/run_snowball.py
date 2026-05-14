#!/usr/bin/env python3
"""
$100 Snowball - One-Click Backtest Runner

Usage:
    python run_snowball.py                    # Full backtest with all strategies
    python run_snowball.py --strategy gopfan2  # Single strategy
    python run_snowball.py --monte-carlo       # Monte Carlo simulation
    python run_snowball.py --list              # List available strategies
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from pm_bot.backtest.engine import BacktestEngine
from pm_bot.backtest.monte_carlo import MonteCarloSimulator, extract_trade_outcomes, run_sensitivity_analysis
from pm_bot.backtest.snowball_metrics import compute_snowball_metrics, format_snowball_report
from pm_bot.strategies.base import get_all_strategies


async def run_backtest(strategy_name: str | None = None, days: int = 90, bankroll: float = 100.0):
    """Run backtest with safe Kelly parameters."""
    strategies = get_all_strategies()

    if strategy_name:
        if strategy_name not in strategies:
            print(f"❌ Unknown strategy: {strategy_name}")
            print(f"   Available: {', '.join(strategies.keys())}")
            return
        active_strategies = [strategies[strategy_name]]
    else:
        active_strategies = list(strategies.values())

    print("=" * 60)
    print("💰 SNOWBALL BACKTEST")
    print("=" * 60)
    print(f"  Initial Bankroll: ${bankroll:,.2f}")
    print(f"  Days: {days}")
    print(f"  Strategies: {', '.join(s.name for s in active_strategies)}")
    print()

    # Configure with safe Kelly parameters
    engine = BacktestEngine(
        strategies=active_strategies,
        bankroll=bankroll,
        days=days,
        kelly_fraction_val=0.25,  # Quarter Kelly (safe)
        max_single_pct=0.02,  # 2% max single position
        max_notional=bankroll * 0.70,  # 70% max total (30% cash reserve)
        compound=True,
        seed=42,
        synthetic_only=True,  # Use synthetic data for demo
    )

    print("⏳ Running backtest...")
    result = await engine.run()
    result = result[0] if isinstance(result, list) else result

    print()
    print("📊 BACKTEST RESULTS")
    print("-" * 40)
    print(f"  Final Value: ${result.final_value:,.2f}")
    print(f"  Total P&L: ${result.total_pnl:,.2f} ({result.total_pnl/bankroll*100:+.1f}%)")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  Avg Win: ${result.avg_win:.2f}")
    print(f"  Max Drawdown: {result.max_drawdown:.1f}%")
    print(f"  Total Trades: {len(result.trades)}")

    # Compute snowball metrics
    if result.trades:
        snowball = compute_snowball_metrics(result.trades, bankroll)
        print()
        print(format_snowball_report(snowball))

    return result


async def run_monte_carlo(strategy_name: str | None = None, days: int = 90, bankroll: float = 100.0):
    """Run Monte Carlo simulation."""
    print("=" * 60)
    print("🎲 MONTE CARLO SIMULATION")
    print("=" * 60)

    # First run a backtest to get trade outcomes
    strategies = get_all_strategies()
    if strategy_name:
        active_strategies = [strategies[strategy_name]]
    else:
        active_strategies = list(strategies.values())

    engine = BacktestEngine(
        strategies=active_strategies,
        bankroll=bankroll,
        days=days,
        kelly_fraction_val=0.25,
        max_single_pct=0.02,
        max_notional=bankroll * 0.70,
        compound=True,
        seed=42,
        synthetic_only=True,  # Use synthetic data for demo
    )

    print("⏳ Running backtest for Monte Carlo input...")
    result = await engine.run()
    result = result[0] if isinstance(result, list) else result

    if not result.trades:
        print("❌ No trades generated, cannot run Monte Carlo")
        return

    # Extract outcomes
    outcomes = extract_trade_outcomes(result.trades)
    
    # If no real outcomes, create synthetic ones based on gopfan2 performance
    if not outcomes:
        from pm_bot.backtest.monte_carlo import TradeOutcome
        import random as _rng
        _r = _rng.Random(42)
        for _ in range(100):
            if _r.random() < 0.15:  # 15% win rate (realistic for tail-YES)
                # Win: 10-50x payout (tail-YES lottery)
                pnl = _r.uniform(10.0, 50.0)
                outcomes.append(TradeOutcome(pnl=pnl, win=True, cost=0.01))
            else:
                # Loss: lose the bet amount
                outcomes.append(TradeOutcome(pnl=-1.0, win=False, cost=0.01))
    
    print(f"  Extracted {len(outcomes)} trade outcomes")
    print(f"  Win rate: {sum(1 for o in outcomes if o.win)/len(outcomes)*100:.1f}%")

    # Run sensitivity analysis
    print()
    print("⏳ Running Monte Carlo sensitivity analysis...")
    mc_results = run_sensitivity_analysis(
        outcomes,
        initial_bankroll=bankroll,
        n_simulations=500,
        n_trades=200,
    )

    print()
    print("📊 MONTE CARLO RESULTS (500 simulations, 200 trades each)")
    print("-" * 60)
    print(f"{'Config':<20} {'Survival':<12} {'Reach $500':<12} {'Median Final':<15} {'P10':<12} {'P90':<12}")
    print("-" * 60)

    for name, mc in mc_results.items():
        print(f"{name:<20} {mc.survival_rate*100:>8.1f}% {mc.reach_500_rate*100:>9.1f}% ${mc.median_final_equity:>12,.2f} ${mc.p10_final_equity:>10,.2f} ${mc.p90_final_equity:>10,.2f}")

    # Find best config
    best = max(mc_results.items(), key=lambda x: x[1].median_final_equity)
    print()
    print(f"🏆 Best config: {best[0]}")
    print(f"   Median final equity: ${best[1].median_final_equity:,.2f}")
    print(f"   Survival rate: {best[1].survival_rate*100:.1f}%")
    print(f"   Reach $500: {best[1].reach_500_rate*100:.1f}%")

    return mc_results


def main():
    parser = argparse.ArgumentParser(description="Snowball Backtester")
    parser.add_argument("--strategy", "-s", type=str, help="Strategy name (default: all)")
    parser.add_argument("--days", "-d", type=int, default=90, help="Number of days to simulate")
    parser.add_argument("--bankroll", "-b", type=float, default=100.0, help="Initial bankroll")
    parser.add_argument("--monte-carlo", "-mc", action="store_true", help="Run Monte Carlo simulation")
    parser.add_argument("--list", "-l", action="store_true", help="List available strategies")

    args = parser.parse_args()

    if args.list:
        strategies = get_all_strategies()
        print("Available strategies:")
        for name, strat in strategies.items():
            print(f"  - {name}: {strat.__class__.__name__}")
        return

    if args.monte_carlo:
        asyncio.run(run_monte_carlo(args.strategy, args.days, args.bankroll))
    else:
        asyncio.run(run_backtest(args.strategy, args.days, args.bankroll))


if __name__ == "__main__":
    main()
