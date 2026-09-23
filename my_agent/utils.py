import requests

SEFARIA_CALENDARS_URL = "https://www.sefaria.org/api/calendars"


def get_coming_jewish_events() -> dict:
    """Fetches this week's Parasha and its short Hebrew description from Sefaria's Calendars API.

    :return: A dict with the Parasha's Hebrew name and a short Hebrew description
    """
    response = requests.get(SEFARIA_CALENDARS_URL, params={"diaspora": "0"})
    response.raise_for_status()
    data = response.json()

    parasha_item = next(
        (
            item
            for item in data.get("calendar_items", [])
            if item.get("title", {}).get("en") == "Parashat Hashavua"
        ),
        None,
    )

    if not parasha_item:
        return {}

    return {
        "parasha": parasha_item.get("displayValue", {}).get("he"),
        "description": parasha_item.get("description", {}).get("he"),
    }


def build_parasha_message(parasha: str, description: str, dvar_torah: str, article_url: str) -> str:
    """Assembles the final WhatsApp message from its fixed parts.

    :param parasha: The Parasha's name
    :param description: The Parasha's short description ("תקציר הפרשה")
    :param dvar_torah: The LLM-generated reflection text ("דבר תורה")
    :param article_url: URL of the source article, appended on its own line
    :return: The fully formatted message text
    """
    return (
        f"*{parasha}*\n\n"
        f"*תקציר הפרשה*\n"
        f"{description}\n\n"
        f"*דבר תורה*\n"
        f"{dvar_torah}\n\n"
        f"{article_url}"
    )
