import html

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
        "parasha_en": parasha_item.get("displayValue", {}).get("en"),
        "description": parasha_item.get("description", {}).get("he"),
    }


def build_parasha_message(
    parasha: str, description: str, dvar_torah: str, article_url: str, style: str = "whatsapp"
) -> str:
    """Assembles the final message from its fixed parts.

    :param parasha: The Parasha's name
    :param description: The Parasha's short description ("תקציר הפרשה")
    :param dvar_torah: The LLM-generated reflection text ("דבר תורה")
    :param article_url: URL of the source article, appended on its own line
    :param style: Formatting of the target channel - "whatsapp" (`*bold*`) or "telegram" (HTML, ending
        with how to unsubscribe from the bot)
    :return: The fully formatted message text
    """
    if style == "telegram":
        def bold(text):
            return f"<b>{text}</b>"
        parasha, description, dvar_torah, article_url = (
            html.escape(part or "") for part in (parasha, description, dvar_torah, article_url)
        )
    else:
        def bold(text):
            return f"*{text}*"

    message = f"{bold(parasha)}\n\n{bold('תקציר הפרשה')}\n{description}"
    if dvar_torah:
        message += f"\n\n{bold('דבר תורה')}\n{dvar_torah}"
    if article_url:
        message += f"\n\n{article_url}"
    if style == "telegram":
        message += "\n\nלהסרה מרשימת התפוצה שלחו /stop"
    return message
