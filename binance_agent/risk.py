from __future__ import annotations

from .config import Settings
from .models import AnalysisResult, MarketSnapshot, TradePlan


class RiskEngine:
    """Convert a five-tier opinion into a bounded Binance Spot trade plan."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_plan(
        self,
        *,
        symbol: str,
        analysis: AnalysisResult,
        market: MarketSnapshot,
        balances: dict[str, dict[str, float]],
    ) -> TradePlan:
        base_asset = symbol.removesuffix(self.settings.quote_asset)
        quote_free = balances.get(self.settings.quote_asset, {}).get("free", 0.0)
        base_free = balances.get(base_asset, {}).get("free", 0.0)
        position_value = base_free * market.price
        equity = quote_free + position_value
        entry = market.price

        if analysis.rating in {"Buy", "Overweight"}:
            action = "BUY"
        elif analysis.rating in {"Sell", "Underweight"}:
            action = "SELL"
        else:
            return self._hold(entry, "The portfolio manager rated this setup Hold")

        if analysis.confidence < self.settings.min_confidence:
            return self._hold(
                entry,
                f"Confidence {analysis.confidence:.0f}% is below the "
                f"{self.settings.min_confidence:.0f}% execution threshold",
            )

        stop_fraction = self.settings.stop_loss_pct / 100
        take_fraction = self.settings.take_profit_pct / 100

        if action == "BUY":
            if equity <= 0 or quote_free <= 0:
                return self._hold(entry, "No available quote balance")
            risk_budget = equity * self.settings.risk_per_trade_pct / 100
            risk_sized_notional = risk_budget / stop_fraction
            max_position_value = equity * self.settings.max_position_pct / 100
            remaining_position_room = max(0, max_position_value - position_value)
            notional = min(
                risk_sized_notional,
                remaining_position_room,
                quote_free / 1.001 * 0.995,
            )
            if notional <= 0:
                return self._hold(entry, "The configured maximum position cap is already reached")
            quantity = notional / entry
            return TradePlan(
                action="BUY",
                executable=True,
                reason=(
                    f"{analysis.rating} passed the confidence gate; size is capped by "
                    "risk budget, available cash, and maximum position exposure"
                ),
                quantity=quantity,
                notional=notional,
                entry_price=entry,
                stop_loss=entry * (1 - stop_fraction),
                take_profit=entry * (1 + take_fraction),
                risk_amount=notional * stop_fraction,
            )

        if base_free <= 0:
            return self._hold(entry, "Spot account has no base asset to sell")
        fraction = 1.0 if analysis.rating == "Sell" else 0.5
        quantity = base_free * fraction
        return TradePlan(
            action="SELL",
            executable=True,
            reason=(
                f"{analysis.rating} passed the confidence gate; the spot-only policy "
                f"reduces {fraction * 100:.0f}% of the available position"
            ),
            quantity=quantity,
            notional=quantity * entry,
            entry_price=entry,
            risk_amount=0,
        )

    @staticmethod
    def _hold(entry: float, reason: str) -> TradePlan:
        return TradePlan(
            action="HOLD",
            executable=False,
            reason=reason,
            entry_price=entry,
        )
