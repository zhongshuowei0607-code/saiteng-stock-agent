# 赛腾股份 · 个人 A 股每日分析 Agent

程序计算事实，LLM 解释事实。本系统仅用于个人研究，不构成投资建议。不连接券商、不下单、不自动修改持仓。

## 最终架构

- `app/config`：环境变量、模型、股票池、观察区间
- `app/data`：统一行情接口，Tushare 优先、AKShare 回退；新闻、公告、基本面和同行
- `app/database`：SQLAlchemy + SQLite，行情与报告按股票/日期幂等写入
- `app/indicators`：Python 技术指标、趋势、支撑压力、企稳评分
- `app/portfolio`：只读持仓与观察状态机
- `app/analysis`：事实汇总、风险、事件、日报
- `app/llm`：OpenAI / DeepSeek / Ollama 统一接口
- `app/api`、`app/web`：FastAPI、Jinja2、ECharts
- `app/scheduler`：上海时区交易日 17:30 调度
- `tests`：分阶段自动测试；`data`、`reports`、`logs`：本地输出

## 安装（Windows PowerShell，Python 3.11+）

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py init-db
python run.py download 603283.SH
python -m pytest -q
```

macOS/Linux：`source .venv/bin/activate`，使用 `cp .env.example .env`。
在 `.env` 填入 TUSHARE_TOKEN；token 不足权限会回退 AKShare，估值缺失保留 null。不得提交 `.env`。

## 数据口径

价格使用不复权日 K，适合当前价和持仓估值，但除权除息会影响跨期技术指标；当前版本明确保留该限制，不能把除权缺口直接当作经营风险。成交量单位为手，金额与市值统一为元，涨跌幅/换手率单位为百分数。请求约 800 个自然日，确保成熟股票通常超过 250 根 K；不足会标记。

官方接口参考：[Tushare](https://tushare.pro/document/2)、[AKShare 股票接口](https://akshare.akfamily.xyz/data/stock/stock.html)。数据源可能有积分、网络或频率限制，失败不会伪造数据。
