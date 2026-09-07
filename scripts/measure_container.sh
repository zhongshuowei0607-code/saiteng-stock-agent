#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
echo "镜像大小："
docker image inspect stock-agent-stock-agent:latest --format '{{.Size}} bytes' 2>/dev/null || docker compose images
echo "容器资源："
docker stats stock-agent --no-stream --format 'Memory={{.MemUsage}} CPU={{.CPUPerc}}'
echo "应用资源："
docker compose exec -T stock-agent python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/system/resources')))"
