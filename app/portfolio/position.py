from decimal import Decimal
from pydantic import BaseModel, Field
class Buy(BaseModel):
    price: Decimal = Field(gt=0)
    shares: int = Field(gt=0)
class Position(BaseModel):
    code: str
    max_shares: int = Field(gt=0)
    buys: list[Buy]
    def valuation(self, price: float | None) -> dict:
        shares = sum(b.shares for b in self.buys)
        cost = sum((b.price*b.shares for b in self.buys),Decimal(0))
        market = None if price is None else Decimal(str(price))*shares
        pnl = None if market is None else market-cost
        return {"shares":shares,"total_cost":float(cost),"average_cost":float(cost/shares) if shares else 0,"market_value":float(market) if market is not None else None,"pnl":float(pnl) if pnl is not None else None,"pnl_pct":float(pnl/cost*100) if pnl is not None and cost else None,"max_shares":self.max_shares,"remaining_shares":max(0,self.max_shares-shares),"position_ratio":shares/self.max_shares,"over_limit":shares>self.max_shares}
