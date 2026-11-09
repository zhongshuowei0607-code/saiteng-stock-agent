from decimal import Decimal
from pydantic import BaseModel, Field

DEFAULT_MAX_SHARES = 1100


class Buy(BaseModel):
    price: Decimal = Field(gt=0, decimal_places=3)
    shares: int = Field(gt=0)


class Position(BaseModel):
    code: str
    max_shares: int = Field(gt=0)
    buys: list[Buy]
    sells: list[Buy] = Field(default_factory=list)

    # Phase 0 account context. These are optional so old portfolio.json files
    # keep loading; missing values are surfaced rather than silently invented.
    account_equity: float | None = Field(default=None, ge=0)
    cash: float | None = Field(default=None, ge=0)
    available_shares: int | None = Field(default=None, ge=0)
    risk_per_trade_pct: float = Field(default=1.0, ge=0.1, le=5)
    atr_stop_multiplier: float = Field(default=2.0, ge=1, le=5)

    def valuation(self, price: float | None) -> dict:
        bought = sum(b.shares for b in self.buys)
        sold = sum(s.shares for s in self.sells)
        shares = max(0, bought - sold)
        gross_cost = sum((b.price * b.shares for b in self.buys), Decimal(0))
        average = gross_cost / bought if bought else Decimal(0)
        cost = average * shares
        market = None if price is None else Decimal(str(price)) * shares
        pnl = None if market is None else market - cost
        market_value = float(market) if market is not None else None

        if self.account_equity is not None:
            equity = float(self.account_equity)
            equity_source = "configured"
        elif market_value is not None and self.cash is not None:
            equity = market_value + float(self.cash)
            equity_source = "cash_plus_market_value"
        elif market_value is not None:
            equity = market_value
            equity_source = "market_value_fallback"
        else:
            equity = None
            equity_source = None

        cash = float(self.cash) if self.cash is not None else None
        cash_source = "configured" if self.cash is not None else None
        if cash is None and equity is not None and market_value is not None:
            cash = max(0.0, equity - market_value)
            cash_source = "derived_from_equity"
        if cash is None:
            cash = 0.0
            cash_source = "missing_fallback"

        available = (
            min(shares, self.available_shares)
            if self.available_shares is not None
            else shares
        )
        return {
            "shares": shares,
            "total_cost": float(cost),
            "average_cost": float(average) if shares else 0,
            "market_value": market_value,
            "pnl": float(pnl) if pnl is not None else None,
            "pnl_pct": float(pnl / cost * 100) if pnl is not None and cost else None,
            "max_shares": self.max_shares,
            "remaining_shares": max(0, self.max_shares - shares),
            "position_ratio": shares / self.max_shares,
            "over_limit": shares > self.max_shares,
            "account_equity": equity,
            "account_equity_source": equity_source,
            "cash": cash,
            "cash_source": cash_source,
            "available_shares": available,
            "available_shares_configured": self.available_shares is not None,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "atr_stop_multiplier": self.atr_stop_multiplier,
        }
