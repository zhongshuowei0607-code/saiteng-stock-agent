# 分阶段交付记录

## Phase 1 — 框架、配置、SQLite、行情

- Python 3.11.15；依赖安装成功。
- `python -m pytest -q`：11 passed。
- `python run.py init-db`：成功。
- `python run.py download 603283.SH`：AKShare 获取 533 个交易日，最新 2026-09-04，已写入 SQLite。
- Tushare 未配置 token，正常回退；Tushare 单位转换用隔离测试验证，未完成真实 token 联调。
- 行情明确不复权；估值与换手率权限失败保留缺失值。
