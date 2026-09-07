#!/bin/sh
set -eu

cd "$(dirname "$0")"
for directory in data logs reports backup config; do
  mkdir -p "$directory"
done

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  echo "已创建 .env。请先填写 Dashboard、Bark、Email、Tushare 或 LLM 配置，然后重新运行本脚本。"
  exit 2
fi

if [ ! -f config/config.yaml ]; then
  cp app/config/config.yaml config/config.yaml
fi
if [ ! -f config/position_strategy.yaml ]; then
  cp app/config/position_strategy.yaml config/position_strategy.yaml
fi

docker compose build
docker compose up -d

attempt=1
while [ "$attempt" -le 30 ]; do
  if docker compose exec -T stock-agent python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)" >/dev/null 2>&1; then
    nas_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "$nas_ip" ] || nas_ip="NAS_IP"
    echo "================================="
    echo "Stock Agent 部署成功"
    echo "Dashboard：http://${nas_ip}:18000"
    echo "测试 Bark：docker compose exec stock-agent python run.py test-bark"
    echo "测试 Email：docker compose exec stock-agent python run.py test-email"
    echo "查看日志：docker compose logs -f"
    echo "================================="
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 5
done

echo "部署未通过健康检查。请运行：docker compose logs --tail=200 stock-agent" >&2
exit 1
