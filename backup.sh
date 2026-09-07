#!/bin/sh
set -eu
cd "$(dirname "$0")"
docker compose exec -T stock-agent python run.py backup
