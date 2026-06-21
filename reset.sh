#!/bin/bash
# seenguid と article をクリア（フィード・興味設定は保持）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${SCRIPT_DIR}/data/news.db"

if [ ! -f "$DB" ]; then
  echo "DB not found: $DB"
  exit 1
fi

echo "以下をクリアします："
echo "  seenguid: $(sqlite3 "$DB" 'SELECT COUNT(*) FROM seenguid') 件"
echo "  article:  $(sqlite3 "$DB" 'SELECT COUNT(*) FROM article') 件"
echo ""
read -p "本当に削除しますか？ [y/N] " ans
if [[ "$ans" != [yY] ]]; then
  echo "キャンセルしました。"
  exit 0
fi

sqlite3 "$DB" "
  DELETE FROM seenguid;
  DELETE FROM article;
  -- etag/last_modified を残すと再ポーリングが 304 になり再取得できないためクリア
  UPDATE feed SET etag = NULL, last_modified = NULL, last_fetched_at = NULL;
"
echo "クリアしました。次回ポーリング時に全記事を再取得・再判定します。"
