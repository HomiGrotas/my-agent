import os
from datetime import date, timedelta

import requests

NEWS_API_URL = "https://newsapi.org/v2/everything"


def _get_credentials():
    """Helper function to load environment variables."""
    api_key = os.environ.get("NEWS_API_KEY")

    if not api_key:
        raise ValueError("Missing required environment variable: NEWS_API_KEY")
    return api_key


def fetch_israeli_news(query: str = "Israel", max_articles: int = 100) -> list[dict]:
    """Fetches news headlines about Israel from the past week.

    :param query: Search terms to filter news by (defaults to "Israel")
    :param max_articles: Maximum number of articles to return (defaults to 100, NewsAPI's page-size cap)
    :return: A list of articles, each with title, description, source, url and published date
    """
    api_key = _get_credentials()
    from_date = (date.today() - timedelta(days=7)).isoformat()

    articles: list[dict] = []
    page = 1
    while len(articles) < max_articles:
        page_size = min(100, max_articles - len(articles))
        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": page_size,
            "page": page,
            "apiKey": api_key,
        }

        response = requests.get(NEWS_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        page_articles = data.get("articles", [])
        if not page_articles:
            break

        articles.extend(page_articles)
        if len(page_articles) < page_size or len(articles) >= data.get("totalResults", 0):
            break
        page += 1

    return [
        {
            "title": article["title"],
            "description": article.get("description"),
            "source": article["source"]["name"],
            "url": article["url"],
            "published_at": article["publishedAt"],
        }
        for article in articles[:max_articles]
    ]
