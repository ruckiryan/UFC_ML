"""Odds conversion and expected value utilities."""


def american_to_payout(odds: float) -> float:
    """Net profit per $1 stake if the bet wins (American odds)."""
    if odds > 0:
        return odds / 100.0
    return 100.0 / -odds


def decimal_to_payout(dec: float) -> float:
    """Net profit per $1 stake if the bet wins (decimal/European odds)."""
    return dec - 1.0


def american_to_implied_prob(odds: float) -> float:
    """Market-implied win probability from American odds."""
    if odds < 0:
        return (-odds) / ((-odds) + 100)
    return 100 / (odds + 100)


def compute_ev(p: float, payout: float) -> float:
    """Expected value per $1 stake given win probability and net payout."""
    return p * payout - (1 - p) * 1.0


def best_ev_multi_book(
    p: float,
    american_odds: list[float],
    decimal_odds: list[float],
) -> float:
    """Best EV across multiple books (American odds for DK/FD, decimal for Pinnacle)."""
    evs = [compute_ev(p, american_to_payout(o)) for o in american_odds]
    evs += [compute_ev(p, decimal_to_payout(d)) for d in decimal_odds]
    return max(evs)
