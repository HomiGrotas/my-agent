import json
import re
from pathlib import Path

ARTICLES_DIR = Path(__file__).resolve().parent.parent.parent / "res" / "parashot_articles"


def _slugify(parasha: str) -> str:
    slug = parasha.strip().lower().replace(" ", "-")
    return re.sub(r"[^a-z0-9-]", "", slug)


def get_parasha_articles(parasha: str) -> list[dict]:
    """Loads previously downloaded Rabbi Jonathan Sacks "Covenant & Conversation" articles for a Parasha.

    Reads from the local `res/parashot_articles/` directory populated by
    `scripts/fetch_sacks_articles.py`, so it does not perform any network calls.

    :param parasha: Name of the Parasha (e.g. "Vayera")
    :return: A list of articles, each with title, full text content, url and published date;
        empty if no local file exists for the Parasha
    """
    articles_path = ARTICLES_DIR / f"{_slugify(parasha)}.json"
    if not articles_path.exists():
        return []

    data = json.loads(articles_path.read_text(encoding="utf-8"))
    return data.get("articles", [])
