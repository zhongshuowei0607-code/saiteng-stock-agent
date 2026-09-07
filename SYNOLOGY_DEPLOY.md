# Synology DS220+ 一键部署

本版本面向 DSM 7.x Container Manager、Intel J4025（linux/amd64）和 2GB 内存。只运行一个容器，使用 SQLite、FastAPI、Jinja2 和静态 ECharts，不含 Node 服务、浏览器、Redis、PostgreSQL、TA-Lib 或本地大型 LLM。

## 方式 A：完全使用 Container Manager（推荐）

1. 在 File Station 创建 `/docker/stock-agent`，上传整个项目。最终实际路径通常为 `/volume1/docker/stock-agent`。
2. 将 `.env.example` 复制为 `.env`。至少确认 `WEB_PORT=18000`；Tushare、Bark、Email 和 LLM 均可暂时留空或关闭。
3. 检查 `config/config.yaml`。默认监控每 180 秒、15:10 更新行情、17:30 生成日报、02:00 备份。
4. 打开 Container Manager → 项目 → 新增，项目名填 `stock-agent`，路径选择 `/docker/stock-agent`，Compose 文件选择 `compose.yaml`。
5. 点击下一步 → 完成，等待 `stock-agent` 容器显示 `healthy`。
6. 浏览器打开 `http://NAS_IP:18000`。首次未配置时进入 `/setup`，完成向导并设置至少 10 位 Dashboard 密码。

不需要 SSH。容器重建或删除后，`data/`、`logs/`、`reports/`、`backup/` 和 `config/` 都保留在 NAS。

## 方式 B：SSH 一键脚本

将项目上传或 `git clone` 到 `/volume1/docker/stock-agent`：

```sh
cd /volume1/docker/stock-agent
chmod +x deploy_synology.sh upgrade_synology.sh backup.sh
./deploy_synology.sh
```

首次运行会创建 `.env` 并要求填写，填写后再运行一次。脚本构建、启动并等待最多 150 秒健康检查。

## 首次向导

向导依次配置数据源、可选 LLM、Bark、Email、默认持仓和 Dashboard 登录。密钥使用持久化随机密钥加密后保存在 SQLite；若 `.env` 同时存在同名配置，环境变量优先。即使不填 Tushare 或 LLM，AKShare、指标、监控、Dashboard、Bark/Email（各自启用时）仍可独立工作。

默认股票为 603283.SH；买入 50×200、48×200，合计 400 股，均价 49 元，最大计划 1000 股，剩余 600 股。

## 通知测试

Container Manager 的容器终端或 SSH 中运行：

```sh
docker compose exec stock-agent python run.py test-bark
docker compose exec stock-agent python run.py test-email
```

Bark 失败或 SMTP 授权码错误不会导致服务退出，详情见 `logs/notification.log`。QQ/163 通常需要邮箱授权码，不是登录密码。

## 安全与外网访问

默认使用 bridge 网络，仅映射 NAS 的 18000 端口。只建议局域网访问，不要配置路由器端口转发。远程访问优先使用 Tailscale；或使用 Synology Reverse Proxy + HTTPS。首次向导会要求 Dashboard 用户名及密码，密码只保存 bcrypt 哈希。

## 数据位置

- 数据库和持仓：`/volume1/docker/stock-agent/data`
- 配置：`/volume1/docker/stock-agent/config`
- 日志：`/volume1/docker/stock-agent/logs`
- 日报：`/volume1/docker/stock-agent/reports`
- 数据库备份：`/volume1/docker/stock-agent/backup`

卸载时在 Container Manager 删除项目/容器和镜像即可。不要删除上述宿主机目录；以后上传新版本并重新创建项目即可恢复数据。

资源验收可在 SSH 中运行 `chmod +x scripts/measure_container.sh && ./scripts/measure_container.sh`，输出镜像大小、容器内存/CPU及应用目录占用。建议分别记录空闲、交易时段和连续运行 7 天后的结果。

构建验收可运行 `./scripts/docker_build_test.sh`。本项目开发主机若没有 Docker，对应 pytest 会明确显示 skipped；应在 DS220+ 或带 Docker 的 CI 上执行后记录镜像大小。

## 升级

先用新版本覆盖程序文件，保留 `.env`、`config/`、`data/`、`logs/`、`reports/`、`backup/`，然后运行：

```sh
chmod +x upgrade_synology.sh
./upgrade_synology.sh
```

脚本先备份数据库，再停止旧容器、重建、启动、执行 migration 并等待健康检查。失败不会删除持久化目录；查看日志后可用升级前 `backup/` 中的数据库恢复。
