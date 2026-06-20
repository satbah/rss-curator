# News Collector

RSS/Atom フィードを定期収集し、ローカル LLM で興味フィルタリングして SQLite に保存する Web アプリ。

## 概要

- **収集**: 登録したフィードを設定間隔（デフォルト60分）でポーリング
- **フィルタリング**: 設定した「興味の説明」をもとにローカル LLM（Ollama）が各記事を判定
- **UI**: ブラウザで記事閲覧・フィード管理・興味設定を行う（HTMX + Tailwind CSS）
- **DB**: SQLite（ローカルファイル）

設計の詳細は [DESIGN.md](DESIGN.md) を参照。

---

## 必要なもの

| ソフトウェア | バージョン | 用途 |
|---|---|---|
| Python | 3.11 以上 | アプリ本体 |
| [uv](https://docs.astral.sh/uv/) | 最新 | パッケージ管理・実行 |
| [Ollama](https://ollama.com/) | 最新 | ローカル LLM サーバー |

### ハードウェア要件（ローカル LLM）

Ollama はデフォルトで `qwen2.5:7b`（Q4_K_M、約 4.5GB）を使用します。

| リソース | 最小 | 推奨 |
|---|---|---|
| RAM | 8GB 空き | 16GB 以上 |
| VRAM | 不要（CPU 推論可） | 6GB 以上で高速化 |
| ストレージ | 6GB（モデルファイル） | — |

GPU VRAM に空きがあれば Ollama が自動的に GPU を活用します。なくても CPU のみで動作します（遅くなります）。

---

## インストール

### 1. uv をインストール

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Ollama をインストール

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

> sudo 権限がない場合は GitHub Releases から tar.zst を取得して展開してください：
> ```bash
> mkdir -p ~/bin
> curl -fsSL https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst \
>   | tar -I zstd -xf - -C ~/bin --wildcards '*/bin/ollama' --strip-components=2
> export PATH="$HOME/bin:$PATH"  # .bashrc/.zshrc にも追加
> ```

### 3. LLM モデルを取得

```bash
# Ollama サーバーを起動（バックグラウンド）
ollama serve &

# モデルを取得（約 4.5GB）
ollama pull qwen2.5:7b
```

軽量モデルを使いたい場合（速度優先、精度やや低下）：

```bash
ollama pull qwen2.5:3b   # 約 2GB
```

その場合は `.env` で `OLLAMA_MODEL=qwen2.5:3b` を設定してください。

### 4. アプリをセットアップ

```bash
cd ~/Work/news
cp .env.example .env
# 必要に応じて .env を編集

uv sync
mkdir -p data
```

---

## 起動

```bash
# Ollama が起動していることを確認
ollama list

# アプリ起動
./restart.sh
```

ブラウザで `http://127.0.0.1:8000` を開く。

### DB を初期化してやり直したい場合

```bash
./reset.sh
```

seenguid（取得済み記事の記録）と article（保存記事）をクリアします。フィード設定・興味設定は保持されます。

---

## 設定

`.env` ファイルで変更できる主な設定：

```env
# Ollama 接続先（デフォルト: ローカル）
OLLAMA_BASE_URL=http://localhost:11434

# 使用モデル（ollama pull で取得したモデル名）
OLLAMA_MODEL=qwen2.5:7b

# 同時推論リクエスト数（Ollama はシングルプロセスなので 2〜4 が目安）
OLLAMA_CONCURRENCY=2

# SQLite DB ファイルパス
DB_PATH=data/news.db

# サーバーのバインドアドレス・ポート
HOST=127.0.0.1
PORT=8000
```

---

## 注意事項

- Ollama は別プロセスとして常時起動が必要です（`ollama serve`）
- モデルの推論速度は CPU のコア数・クロック周波数に依存します
- 記事の判定は「合致 / 非合致」の二値で、不合致と判定された記事は保存されません
- 一度処理した記事は再判定されません（`seenguid` テーブルで管理）
