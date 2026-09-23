import json
import re
from pathlib import Path

ARTICLES_DIR = Path(__file__).resolve().parent.parent.parent / "res" / "parashot_articles"


def _slugify(parasha: str) -> str:
    slug = parasha.strip().lower().replace(" ", "-")
    return re.sub(r"[^a-z0-9-]", "", slug)


# Sefaria calendar spellings whose slug differs from the local file name
PARASHA_SLUG_ALIASES = {
    "shlach": "shelach-lecha",
}


# Prefixes of Sefaria's holiday reading names (e.g. "Sukkot I", "Pesach Shabbat Chol haMoed")
# -> the slug of the holiday's article file
HOLIDAY_READING_SLUGS = {
    "rosh-hashana": "rosh-hashana",
    "yom-kippur": "yom-kippur",
    "sukkot": "sukkot",
    "shmini-atzeret": "sukkot",
    "simchat-torah": "sukkot",
    "pesach": "pesach",
    "shavuot": "shavuot",
}


def _parasha_slugs(parasha: str, rabbi_dir: Path) -> list[str]:
    """Maps a Parasha or holiday reading name to the slugs of its local article files.

    Holiday readings (e.g. Sefaria's "Sukkot I") map to their holiday's file. Combined readings
    (e.g. "Matot-Masei") map to one slug per Parasha, but only when the whole name has no file
    of its own, since some single names are hyphenated too (e.g. "Lech-Lecha").
    """
    slug = _slugify(parasha)
    for prefix, holiday_slug in HOLIDAY_READING_SLUGS.items():
        if slug.startswith(prefix):
            return [holiday_slug]
    slug = PARASHA_SLUG_ALIASES.get(slug, slug)
    if (rabbi_dir / f"{slug}.json").exists() or "-" not in parasha:
        return [slug]
    parts = (_slugify(part) for part in parasha.split("-"))
    return [PARASHA_SLUG_ALIASES.get(part, part) for part in parts]


def _normalize_rabbi(rabbi: str) -> str:
    name = re.sub(r"[\s-]+", "_", rabbi.strip().lower())
    return re.sub(r"[^a-z0-9_]", "", name)


def list_rabbis() -> list[str]:
    """Lists the Rabbis whose Parasha articles are available locally.

    :return: Rabbi identifiers, one per subdirectory of `res/parashot_articles/` (e.g. "sacks")
    """
    return sorted(path.name for path in ARTICLES_DIR.iterdir() if path.is_dir())


PREVIEW_CHARS = 400


def _load_articles(parasha: str, rabbi: str) -> list[dict]:
    """Loads previously downloaded Parasha articles written by the given Rabbi.

    Reads from the local `res/parashot_articles/<rabbi>/` directory populated by the
    `scripts/fetch_*_articles.py` scripts, so it does not perform any network calls.

    :param parasha: Name of the Parasha as in Sefaria's calendar (e.g. "Vayera"); a combined
        reading (e.g. "Matot-Masei") returns the articles of both Parashot
    :param rabbi: Rabbi identifier as returned by `list_rabbis()` (e.g. "sacks"); spaces,
        hyphens and case are normalized, and a unique partial match (e.g. "rahav meir" or
        "Rabbi Shlomo Riskin") is accepted
    :return: A list of articles, each with title, text, url and published date;
        empty if no local file exists for the Parasha
    :raises ValueError: If no single Rabbi matches the given name
    """
    wanted = _normalize_rabbi(rabbi)
    rabbis = list_rabbis()
    matches = [name for name in rabbis if name == wanted] or [
        name for name in rabbis if wanted in name or name in wanted
    ]
    if len(matches) != 1:
        raise ValueError(f"Unknown Rabbi '{rabbi}'. Available: {', '.join(rabbis)}")

    rabbi_dir = ARTICLES_DIR / matches[0]
    articles = []
    for slug in _parasha_slugs(parasha, rabbi_dir):
        articles_path = rabbi_dir / f"{slug}.json"
        if articles_path.exists():
            data = json.loads(articles_path.read_text(encoding="utf-8"))
            articles.extend(data.get("articles", []))
    return articles


def list_parasha_articles(parasha: str, rabbi: str) -> list[dict]:
    """Lists a Rabbi's articles for a Parasha as short previews, without their full text.

    :param parasha: Name of the Parasha (e.g. "Vayera")
    :param rabbi: Rabbi identifier, matched as in `_load_articles()`
    :return: A list of articles, each with index, title, a short text preview and published date;
        empty if no local file exists for the Parasha
    :raises ValueError: If no single Rabbi matches the given name
    """
    return [
        {
            "index": index,
            "title": article.get("title"),
            "preview": article.get("text", "")[:PREVIEW_CHARS],
            "published_at": article.get("published_at"),
        }
        for index, article in enumerate(_load_articles(parasha, rabbi))
    ]


def get_parasha_article(parasha: str, rabbi: str, index: int) -> dict:
    """Loads a single full article by its index from `list_parasha_articles()`.

    :param parasha: Name of the Parasha (e.g. "Vayera")
    :param rabbi: Rabbi identifier, matched as in `_load_articles()`
    :param index: Index of the article as returned by `list_parasha_articles()`
    :return: The article with title, text, url and published date
    :raises ValueError: If no single Rabbi matches the given name or the index is out of range
    """
    articles = _load_articles(parasha, rabbi)
    if not 0 <= index < len(articles):
        raise ValueError(
            f"No article at index {index} for Parasha '{parasha}' by '{rabbi}'. "
            f"Valid indexes: 0-{len(articles) - 1}" if articles else
            f"No articles found for Parasha '{parasha}' by '{rabbi}'"
        )
    return articles[index]
