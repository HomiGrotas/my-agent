import json
import re
from pathlib import Path

ARTICLES_DIR = Path(__file__).resolve().parent.parent.parent / "res" / "parashot_articles"


def _slugify(parasha: str) -> str:
    slug = parasha.strip().lower().replace(" ", "-")
    return re.sub(r"[^a-z0-9-]", "", slug)


def _normalize_rabbi(rabbi: str) -> str:
    name = re.sub(r"[\s-]+", "_", rabbi.strip().lower())
    return re.sub(r"[^a-z0-9_]", "", name)


def list_rabbis() -> list[str]:
    """Lists the Rabbis whose Parasha articles are available locally.

    :return: Rabbi identifiers, one per subdirectory of `res/parashot_articles/` (e.g. "sacks")
    """
    return sorted(path.name for path in ARTICLES_DIR.iterdir() if path.is_dir())


def get_parasha_articles(parasha: str, rabbi: str) -> list[dict]:
    """Loads previously downloaded Parasha articles written by the given Rabbi.

    Reads from the local `res/parashot_articles/<rabbi>/` directory populated by the
    `scripts/fetch_*_articles.py` scripts, so it does not perform any network calls.

    :param parasha: Name of the Parasha (e.g. "Vayera")
    :param rabbi: Rabbi identifier as returned by `list_rabbis()` (e.g. "sacks"); spaces,
        hyphens and case are normalized, and a unique partial match (e.g. "rahav meir" or
        "Rabbi Shlomo Riskin") is accepted
    :return: A list of articles, each with title, full text content, url and published date;
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

    articles_path = ARTICLES_DIR / matches[0] / f"{_slugify(parasha)}.json"
    if not articles_path.exists():
        return []

    data = json.loads(articles_path.read_text(encoding="utf-8"))
    return data.get("articles", [])
