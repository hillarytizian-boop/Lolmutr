from app.profit import (
    effective_stop,
    exit_reason,
    profit_size_pct,
    ratchet_high,
    trailing_stop,
)


def test_take_profit_hits():
    assert (
        exit_reason(mark=110, take=108, hard_stop=95, high=110, atr=2, trail_mult=1.4)
        == "take-profit"
    )


def test_hard_stop_hits():
    assert (
        exit_reason(mark=94, take=110, hard_stop=95, high=100, atr=2, trail_mult=1.4)
        == "stop-loss"
    )


def test_trailing_stop_locks_in_gain():
    # high 110, ATR 2, trail 1.4 → stop 107.2, above the hard 95
    why = exit_reason(mark=107, take=120, hard_stop=95, high=110, atr=2, trail_mult=1.4)
    assert why == "trailing-stop"


def test_stays_in_when_between_stop_and_target():
    assert (
        exit_reason(mark=102, take=110, hard_stop=95, high=103, atr=2, trail_mult=1.4)
        is None
    )


def test_ratchet_and_trail():
    assert ratchet_high(100, 104) == 104
    assert trailing_stop(110, 2, 1.5) == 107
    assert effective_stop(95, 110, 2, 1.5) == 107


def test_high_conviction_buy_is_larger():
    meek = profit_size_pct("Buy", 0.55, 1.0)
    hot = profit_size_pct("Buy", 0.85, 1.0)
    hold = profit_size_pct("Hold", 0.9, 1.0)
    assert hot > meek > 0
    assert hold == 0
    assert hot <= 0.20


def test_ten_dollar_book_commits_almost_all_cash():
    size = profit_size_pct("Buy", 0.7, 1.0, small_account=True)
    assert size >= 0.9
    assert profit_size_pct("Buy", 0.4, 1.0, small_account=True) == 0


def test_goal_and_floor():
    from app.profit import goal_reached, too_small_to_trade

    assert goal_reached(50, 50)
    assert goal_reached(51.2, 50)
    assert not goal_reached(49.9, 50)
    assert too_small_to_trade(4.5, 5)
    assert not too_small_to_trade(10, 5)
