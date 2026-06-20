"""初期データ（フィード・興味）を投入する冪等シードスクリプト。

使い方:
    uv run python -m app.seed

既に同じ URL のフィード／同じ名前の興味があればスキップするため、
何度実行しても重複登録されません。フィードの URL は RSSs.md を参照。
"""

from app.models import Feed, Interest, init_db

# (name, url) — interval はデフォルト 60 分
FEEDS: list[tuple[str, str]] = [
    # IT・AI 技術（日本語）
    ("Yahoo!ニュース 科学", "https://news.yahoo.co.jp/rss/categories/science.xml"),
    ("ITmedia AI＋", "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml"),
    ("ITmedia News 速報", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("Publickey", "https://www.publickey1.jp/atom.xml"),
    # IT・AI 技術（英語）
    ("TechCrunch", "https://feeds.feedburner.com/TechCrunch"),
    ("WIRED", "https://www.wired.com/feed/rss"),
    ("Hacker News Front Page", "https://hnrss.org/frontpage"),
    ("arXiv cs.AI", "https://arxiv.org/rss/cs.AI"),
    # 株価・経済動向（日本語）
    ("日本取引所グループ マーケットニュース", "https://www.jpx.co.jp/rss/markets_news.xml"),
    ("Yahoo!ニュース 経済", "https://news.yahoo.co.jp/rss/categories/business.xml"),
    ("日本経済新聞", "https://www.nikkei.com/rss/news.rdf"),
    ("ITmedia ビジネス AnchorDesk", "https://rss.itmedia.co.jp/rss/2.0/anchordesk.xml"),
    # 株価・経済動向（英語）
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("Financial Times", "https://www.ft.com/?format=rss"),
    ("Reuters Business News", "https://feeds.reuters.com/reuters/businessNews"),
    ("Investing.com News", "https://www.investing.com/rss/news.rss"),
]

# (name, description) — description が LLM の興味判定基準になる
INTERESTS: list[tuple[str, str]] = [
    (
        "AI・IT技術",
        "生成AI・大規模言語モデル・機械学習の研究や新モデル、AIを活用した製品・サービス、"
        "半導体やGPUなどのAIインフラ、注目のソフトウェア技術やプログラミング、"
        "主要IT企業（OpenAI・Google・Anthropic・Apple・NVIDIAなど）の技術動向に関する記事。",
    ),
    (
        "株価・経済動向",
        "日米の株式市場の動向、主要株価指数（日経平均・TOPIX・S&P500など）、"
        "金利・為替・金融政策（日銀・FRB）、注目企業の決算や業績、"
        "マクロ経済指標やインフレ・景気動向に関する記事。特にIT・半導体・AI関連銘柄の市況。",
    ),
]


def seed() -> None:
    init_db()

    added_feeds = 0
    for name, url in FEEDS:
        _, created = Feed.get_or_create(url=url, defaults={"name": name})
        added_feeds += int(created)

    added_interests = 0
    for name, description in INTERESTS:
        existing = Interest.select().where(Interest.name == name).first()
        if existing is None:
            Interest.create(name=name, description=description)
            added_interests += 1

    print(f"feeds:     +{added_feeds} (total {Feed.select().count()})")
    print(f"interests: +{added_interests} (total {Interest.select().count()})")


if __name__ == "__main__":
    seed()
