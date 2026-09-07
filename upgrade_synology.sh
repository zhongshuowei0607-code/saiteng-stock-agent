#!/bin/sh
set -eu
cd "$(dirname "$0")"

echo "[1/6] 备份数据库"
if docker compose ps --status running --services | grep -qx stock-agent; then
  docker compose exec -T stock-agent python run.py backup
elif [ -f data/stock_agent.db ]; then
  mkdir -p backup
  stamp=$(date +%Y%m%d_%H%M%S)
  cp data/stock_agent.db "backup/pre_upgrade_${stamp}.db"
  echo "容器未运行，已复制数据库；建议启动旧版本后执行在线备份再升级。"
fi

echo "[2/6] 停止旧容器"
docker compose stop stock-agent || true

echo "[3/6] 重建镜像"
docker compose build

echo "[4/6] 启动新版本"
docker compose up -d

echo "[5/6] 执行数据库 migration"
docker compose exec -T stock-agent python run.py migrate

echo "[6/6] 健康检查"
attempt=1
while [ "$attempt" -le 30 ]; do
  if docker compose exec -T stock-agent python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)" >/dev/null 2>&1; then
    echo "升级成功。VERSION=$(cat VERSION)；data、logs、reports、backup 均已保留。"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 5
done

echo "升级后健康检查失败。数据未删除；请运行 docker compose logs --tail=200 stock-agent。升级前备份位于 backup/。" >&2
exit 1
