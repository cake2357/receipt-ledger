#!/bin/zsh
set -euo pipefail
cd -- "$(dirname -- "$0")"
umask 077
if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  UV="$HOME/.local/bin/uv"
else
  print 'uv が必要です: https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
fi
print 'レシート家計簿を起動します（標準URL: http://127.0.0.1:8765）。実際のURLは下のUvicornログを確認。終了は Ctrl+C。'
exec "$UV" run --frozen python server.py
