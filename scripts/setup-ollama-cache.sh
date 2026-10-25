#!/usr/bin/env bash
# Setup helper: reuses an existing Ollama model volume so the local models aren't re-downloaded
# Detects whether the original `customer-compass` repo's Ollama model cache
# already exists as a Docker volume on this machine. If it does, points this
# repo's `ollama` service at that same volume (via OLLAMA_VOLUME_NAME in
# .env) so qwen2.5:3b / mxbai-embed-large don't need to be re-downloaded.
# If no prior cache is found, a fresh volume name is written instead and
# models will be pulled on first use, as normal.
#
# Usage: run once before `docker compose up`:
#   ./scripts/setup-ollama-cache.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
LEGACY_VOLUME="customer-compass_ollama-data"
FRESH_VOLUME="customer-compass-v2_ollama-data"

if docker volume inspect "$LEGACY_VOLUME" >/dev/null 2>&1; then
  echo "✓ Found an existing Ollama model cache from customer-compass (v1): $LEGACY_VOLUME"
  echo "  Reusing it — qwen2.5:3b / mxbai-embed-large will not be re-downloaded."
  VOLUME_NAME="$LEGACY_VOLUME"
else
  echo "No existing Ollama cache found on this machine."
  echo "A fresh volume ($FRESH_VOLUME) will be created; models will be pulled on first use."
  VOLUME_NAME="$FRESH_VOLUME"
fi

if [ -f "$ENV_FILE" ] && grep -q "^OLLAMA_VOLUME_NAME=" "$ENV_FILE"; then
  sed -i.bak "s/^OLLAMA_VOLUME_NAME=.*/OLLAMA_VOLUME_NAME=$VOLUME_NAME/" "$ENV_FILE"
  rm -f "$ENV_FILE.bak"
else
  echo "OLLAMA_VOLUME_NAME=$VOLUME_NAME" >> "$ENV_FILE"
fi

echo "OLLAMA_VOLUME_NAME=$VOLUME_NAME written to $ENV_FILE"
