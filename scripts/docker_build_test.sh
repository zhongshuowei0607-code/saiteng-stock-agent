#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker build --platform linux/amd64 -t stock-agent:build-test .
echo "linux/amd64 镜像构建成功"
