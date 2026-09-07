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

## Phase 3 — LLM、风险与日报

- 累计测试：25 passed；缓存真实行情完整生成 2026-09-07 Markdown / HTML 日报并入库。
- OpenAI Compatible 与 Ollama 接口、Pydantic JSON 校验、事件引用校验、禁止即时交易措辞校验已实现。
- 未配置云端 Key / 本地模型，真实 AI 生成未验证；离线降级明确标识，不伪称 AI 结果。
- 风险模型是可解释启发式；报告披露缺失因子及覆盖率。

## Phase 4 — 事件、新闻、财务与同行

- 累计测试：29 passed，修复 Pandas pct_change 字段与方法重名问题。
- 真实联网联调成功获取 15 条个股/同行新闻样本、12 期财务（包含 2026 半年报），保存入库。
- 此次巨潮公告接口与六只同行行情失败，已展示缺失及具体源状态；市场刷新代理失败后使用 Phase 1 的真实缓存。
- 整体任务约 34 秒完成，LLM 不可用时仍成功输出日报。
- 不将只有个股、没有同行的样本视为行业信号；原文截断和标题级分析有显式标识。

## Phase 5 — FastAPI Dashboard 与 API

- 累计测试：30 passed（依赖库两项弃用警告，非应用失败）。
- 实际启动 `python run.py`，本地首页 HTTP 200。
- ECharts 静态资源本地化，包含 K 线/均线、成交量、MACD、持仓/企稳/风险、新闻公告、财务、同行与历史日报。
- API 测试覆盖全部指定 GET、同源写请求校验、并发分析冲突、非法股票和报告路径。

## Phase 6 — 交易日调度

- 累计测试：32 passed。
- APScheduler 使用 Asia/Shanghai 17:30、max_instances=1、合并错过触发；应用关闭时停止调度。
- Tushare 日历优先，AKShare 回退，持久化已验证覆盖范围；周末和已知节假日跳过，覆盖之外且抓取失败返回未知并跳过。
- `python run.py daily` 使用同一交易日判断；`analyze` 为显式手动运行。

## Phase 7 — 故障处理、回归测试与交付

- 最终累计 `pytest -q`：47 passed，2 条上游 Starlette / AnyIO 弃用提示。
- Ruff 未使用名称/变量检查通过；所有 Python 源码统一格式化，公开函数与构造函数补充类型标注。
- Dashboard JavaScript 通过 Node `--check`；最终服务首页、持仓/技术指标/日报列表/状态 API、HTML 日报、本地 ECharts 共 7 项真实 HTTP 检查均为 200。
- 最终真实数据：533 根日 K（最新 2026-09-04）、15 条新闻、11 条公告、3 条官方公告 PDF 原文、12 期财务。生成 2026-09-07 Markdown/HTML；页面与 SQLite 已核对。
- 当前持仓 400 股，成本 49 元，最大 1000 股，剩余 600 股。
- 硬超时、有限重试、跨进程锁、原子写文件、配置区间校验、HTML 活动内容过滤、LLM 新增数值校验、缓存补充资料保留、跨日日志已覆盖。
- 增加 Tushare moneyflow 因子和单位测试；无 Token 时保持缺失。
- 已提供 Windows start.bat、Dockerfile / compose.yaml、精确依赖快照和完整运行说明。

### 实际限制与待用户环境验证

- 未提供 Tushare Token；Tushare 真实行情/估值/财务/资金流权限尚未验证，接口映射与降级经测试。
- 未配置可用 OpenAI / DeepSeek Key 或 Ollama 模型；三种请求协议通过隔离测试，真实模型解释显示“AI 未生成”。
- 东方财富行情接口在后续联调间歇出现 ProxyError。个股使用已下载真实缓存；六只同行本次未取得同日行情，因此不输出行业强弱结论。
- 运行验证环境 macOS + Python 3.11.15；Windows 与 Docker/NAS 文件已提供，当前无 Docker 命令，未声称完成这些平台实机验证。
- 不复权指标、标题事件初筛、日线成交密集区、候选同行池与启发式风险评分均非经过回测验证的交易策略。

## macOS 一键启动补充

- 新增可双击 `start.command`，就绪后自动打开浏览器，已有服务直接复用。
- 修复原虚拟环境 Python 指向失效 `/tmp` 路径的问题；自动备份旧环境并用本机 Python 重建。
- 实际重建为 Python 3.14.5，依赖安装成功，启动后首页与技术指标 API 返回 HTTP 200。
- 新增失效环境备份重建、已有环境免安装测试；累计 49 passed（2 条上游弃用提示）。
