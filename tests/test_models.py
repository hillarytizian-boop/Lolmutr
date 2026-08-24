from app.models import rating_size_pct, rating_to_action


def test_rating_to_action():
    assert rating_to_action("Buy") == "Buy"
    assert rating_to_action("Overweight") == "Buy"
    assert rating_to_action("Hold") == "Hold"
    assert rating_to_action("Underweight") == "Sell"
    assert rating_to_action("Sell") == "Sell"


def test_size_is_zero_when_not_adding():
    assert rating_size_pct("Hold") == 0
    assert rating_size_pct("Sell") == 0
    assert rating_size_pct("Buy") > rating_size_pct("Overweight") > 0
