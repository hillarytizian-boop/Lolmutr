from market.news import fetch_news_bundle
from market.sentiment import fetch_sentiment


def test_news_401_does_not_raise(monkeypatch):
    import market.news as news

    def boom(*_a, **_k):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(news, "_cryptocompare", boom)
    monkeypatch.setattr(news, "_rss", boom)
    bundle = fetch_news_bundle()
    assert bundle.headlines == []
    assert "cryptocompare" in bundle.providers_down
    assert "fabricat" in bundle.note.lower() or not bundle.headlines


def test_sentiment_unavailable_is_not_invented(monkeypatch):
    import market.sentiment as sent
    import httpx

    def fail(*_a, **_k):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(sent.httpx, "get", fail)
    bundle = fetch_sentiment()
    assert bundle.value is None
    assert bundle.status == "DEGRADED"
    assert "invent" in bundle.note.lower() or "unavailable" in bundle.note.lower()
