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

## 启动与分析

```powershell
python run.py                    # Web： http://127.0.0.1:8000
python run.py analyze 603283.SH   # 完整实时抓取、解释和报告
python run.py daily               # 确认当天是交易日才运行
python run.py analyze --offline   # 缓存研究，不访问网络或 LLM
python -m pytest -q               # 全部自动测试
```

Windows 也可以双击 `start.bat`（先完成环境安装）。`download` 只下载行情，不生成报告；已有报告打开页面即可查看，点击“更新并生成日报”运行完整流程。首次启动没有报告时创建缺失/缓存报告，需点击更新才抓取网络数据。Web 服务默认仅绑定本机，不提供远程账户系统。

## macOS 一键运行

在 Finder 中双击项目目录下的 `start.command`。脚本会自动进入项目目录、使用 `.venv`，并在服务就绪后打开默认浏览器。已有本工具服务时直接打开页面，不重复启动。

首次运行需要 Python 3.11+；缺少或失效的虚拟环境会自动重建，旧环境保留为 `.venv.backup-*`；缺少依赖时自动安装（需要联网），没有 `.env` 时从示例创建。API Key 和模型仍需按下文配置。请保留启动的终端窗口，按 `Control+C` 停止服务。

若 macOS 阻止首次打开，可右键 `start.command` → 打开。复制项目后若执行权限丢失，在项目目录运行 `chmod +x start.command`。端口 8000 被其他程序占用时会提示错误，不会关闭其他程序。

## 模型配置

默认 `app/config/config.yaml` 为 Ollama / qwen3。安装 Ollama 后先运行 `ollama pull qwen3`，确保 Ollama 服务正在运行。在 `.env` 设置 `OLLAMA_URL=http://localhost:11434`。

OpenAI 示例（密钥只填 `.env`）：

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=填写账户实际可用的模型名称
OPENAI_API_KEY=你的密钥
```

DeepSeek 使用 `LLM_PROVIDER=deepseek`、`LLM_MODEL=deepseek-chat`、`DEEPSEEK_API_KEY=...`。`LLM_PROVIDER=disabled` 关闭模型解释。环境变量覆盖 YAML 中模型设置。切换云模型会将报告事实与持仓数据发送到选择的模型供应商。Chat Completions 接口采用 JSON 模式，再由 Pydantic 验证：[OpenAI 官方接口](https://developers.openai.com/api/reference/cli/resources/chat)。没有可用模型时仍生成报告，并显式标注 AI 未生成。

模型没有搜索或交易工具。提示词禁止外部知识补齐事实；输出校验 JSON 结构、事件 ID、即时交易措辞和未提供数值。校验是保守防线，不能证明所有自然语言解释都正确，须结合页面来源核对。

## 持仓与观察区配置

`data/portfolio.json` 保存用户提供的两笔买入。所有运行入口只读取它，不会修改。分红、送转、费用或人工交易后的持仓变化需要用户手工维护。成本未含手续费和现金分红，计划仓位是股数 / 1000，并非账户总资产仓位。

`app/config/position_strategy.yaml` 配置价格区间，左闭右开，例如 42.00 进入第一加仓观察区，43.00 进入持仓观察。阈值只决定观察信号，不生成买卖指令。突破确认要求连续两日站上此前 20 日高点且当日相对五日均量放量。只有标题的事件不得触发 LLM 投资逻辑判断；可用事件解释要求暂停补仓观察时，会覆盖为高风险状态。

## 自动任务

Web 服务运行期间，APScheduler 每天上海时间 17:30 检查交易日历并执行。Tushare 日历优先，AKShare 日历回退；缓存覆盖之外且获取失败时跳过。电脑关机或程序退出就不会运行，不会自动补跑关机期间的任务。应只运行一个 Web worker；操作系统文件锁同时防止 Web、CLI 和调度并发写报告。

Windows 可用任务计划程序在工作日 17:30 执行 `.venv\Scripts\python.exe run.py daily`，起始目录设为项目目录；由程序进一步排除法定休市日。若采用任务计划程序，请在 YAML 将 `scheduler.enabled` 设为 false，避免两个调度来源。

## 报告与数据

- `data/stock_agent.db`：日线、公告/新闻、财务和日报 JSON，按键幂等更新。
- `reports/603283/YYYY-MM-DD.md` 与 `.html`：按生成日保存，报告单独显示行情日期。当天重复运行更新同一份报告。
- `logs/stock_agent_YYYYMMDD.log`：行情源失败、请求、LLM 状态和任务耗时。不记录密钥或完整模型请求。
- Tushare 日线估值/财务需要对应权限；AKShare 日线不提供历史 PE/PB/市值时保持缺失。
- 公告取最近 45 日、最多 15 条，尝试提取最新 3 条官方 PDF 的前 80 页；原文/截断状态可见。模型输入每条原文最多 12000 字符，数据库保留提取到的全文。
- 新闻为实际抓取的个股新闻加一只同行新闻样本，非完整行业新闻覆盖。提供来源、时间、URL 和去重 ID。
- 财务保存最近 12 期，优先使用截至运行日已公告的数据；增长比较同年内对应报告期，不用单季度与全年混比。这不是带历史财务修订快照的回测系统。
- 同行须与赛腾最新行情日期对齐；缺失或停牌导致日期不一致会排除；样本不足时不给行业结论。
- 风险 0–100 为启发式权重归一化，展示可用因子覆盖率和缺失项。资金流采用 Tushare moneyflow，须有权限且日期对齐，17:30 时可能尚未发布，不会用成交量伪装资金净流入；估值阈值未作行业历史分位校准。

## Docker / NAS

```sh
cp .env.example .env
# 配置密钥、模型，再启动：
docker compose up -d --build
```

容器仅向宿主机 `127.0.0.1:8000` 发布端口，数据目录持久化。NAS 文件夹需授予容器用户写权限。宿主机 Ollama 在容器中不能用 `localhost`，Docker Desktop 可配置 `OLLAMA_URL=http://host.docker.internal:11434`；Linux/NAS 请按其网关地址配置。默认不暴露到互联网；需要远程使用时应另设认证反向代理，并在 TrustedHost 配置加入明确域名。本次验证环境为 macOS Python 3.11，Windows 和 Docker 尚未做真实机器验收。

## 常见错误

- Tushare ValueError：没有 Token，检查 `.env`；权限错误按源提示检查积分与接口权限，系统继续回退。
- ProxyError / TimeoutExpired：检查网络与代理；外部接口在子进程中有硬超时，可以继续用缓存。缓存不会标记为今天收盘数据。
- 只有 400 股/49 元，价格为 `—`：尚未取得行情，点击更新或运行 `download` 后 `analyze`。
- AI 未生成：检查模型名、API Key、Ollama 是否启动；JSON 或安全校验失败也会拒绝采用模型输出。
- 自动任务未运行：确认进程在 17:30 存活、日历覆盖当前年份、机器时钟和网络正常。
- 端口占用：关闭已有实例，避免双开。不要开多个 Uvicorn worker。
- PowerShell 不允许激活脚本：直接使用 `.venv\Scripts\python.exe` 和 `.venv\Scripts\pip.exe`。
- 测试显示 Starlette / AnyIO 弃用警告：目前是上游兼容性提示，不影响测试结果。

各阶段提交与实际验证结果见 `PHASES.md`。全部测试使用临时数据库和独立测试数据，不会把测试行情写入实际持仓报告。

`requirements-lock.txt` 记录本次验证的精确依赖版本；同环境复现可用 `pip install -r requirements-lock.txt`。
