# 分阶段交付记录

## Phase 1 — 框架、配置、SQLite、行情

- Python 3.11.15；依赖安装成功。
- `python -m pytest -q`：11 passed。
- `python run.py init-db`：成功。
- `python run.py download 603283.SH`：AKShare 获取 533 个交易日，最新 2026-09-04，已写入 SQLite。
- Tushare 未配置 token，正常回退；Tushare 单位转换用隔离测试验证，未完成真实 token 联调。
- 行情明确不复权；估值与换手率权限失败保留缺失值。

## Phase 2 — 指标、持仓、状态机、企稳

- 累计测试：22 passed。
- 验证 MA 暖机、MACD 独立递推、RSI 上涨/下跌/横盘边界、支撑压力方向、趋势、持仓与盈亏、六个价格边界、弱企稳不确认。
- 实现全部要求的指标；支撑压力为 ATR 聚类的启发式估计。
