import os

import logfire
from pydantic_ai import Agent

from my_agent.tools.fetch_israeli_news import fetch_israeli_news
from my_agent.tools.get_parasha_articles import get_parasha_articles
from my_agent.tools.send_whatsapp_message import send_whatsapp_message
from my_agent.utils import build_parasha_message, get_coming_jewish_events

logfire.configure(service_name="my-agent")
logfire.instrument_pydantic_ai()

jewish_events = get_coming_jewish_events()

agent = Agent(
    'google:gemini-3.5-flash-lite',
    instructions=(
        f"You are a Jewish assistant that delivers personalized Parashat HaShavua (weekly Torah portion) messages via WhatsApp/SMS.\n\n"

        f"## Your Workflow\n"
        f"Follow these steps in order:\n"
        f"1. **Gather current news** – Use your tool to fetch Israeli news headlines from the past week."
        f"Use the news in an optimistic way only. Use only articles relevant for the Parasha, no more than 3.\n"
        f"2. **Gather Parasha source material** – Use your tool to fetch Rabbi Jonathan Sacks' "
        f"\"Covenant & Conversation\" articles for the current Parasha, and draw on their themes and insights.\n"
        f"3. **Write the דבר תורה** – Write a meaningful, insightful reflection that draws a thoughtful, "
        f"relevant connection between the Parasha and one or more current news events, and ends with a "
        f"practical lesson or question for reflection (דבר תורה style). It should be warm, respectful, "
        f"accessible to a general Jewish audience, and concise enough for a text message (under 1300 words). "
        f"Do not write a title, headers, or a link yourself — write only the דבר תורה body text.\n"
        f"4. **Send the message** – Call your send tool with the דבר תורה text and the exact `url` field of "
        f"the Parasha article you drew from (if you used more than one, use the url of the first/primary one). "
        f"The rest of the message is assembled automatically.\n\n"

        f"## Tone & Style\n"
        f"- Hebrew only\n"
        f"- Respectful and inclusive of all Jewish denominations\n"
        f"- Engaging, not preachy\n"

        f"## Jewish Calendar Context\n"
        f"{jewish_events}\n\n"

        f"The current Parasha and any upcoming holidays are listed above. "
        f"If a major event is approaching, weave it into the message alongside the Parasha."
    ),
)


@agent.tool_plain
def fetch_israeli_news_headlines(query: str = "Israel", max_articles: int = 100) -> list[dict]:
    """Fetch Israeli news headlines from the past week to inform the Parasha message.

    :param query: Search terms to filter news by (defaults to "Israel")
    :param max_articles: Maximum number of articles to return (defaults to 100)
    :return: A list of recent articles with title, description, source, url and published date
    """
    return fetch_israeli_news(query, max_articles)


@agent.tool_plain
def fetch_parasha_articles(parasha: str) -> list[dict]:
    """Fetch Rabbi Jonathan Sacks "Covenant & Conversation" articles for a Parasha to inform the message.

    :param parasha: Name of the Parasha (e.g. "Vayera")
    :return: A list of articles with title, full text content, url and published date
    """
    return get_parasha_articles(parasha)


@agent.tool_plain
def send_parasha_whatsapp(recipient_phone: str, dvar_torah: str, article_url: str) -> str:
    """Assemble the Parasha message from its template and send it via WhatsApp.

    :param recipient_phone: Recipient's phone number in international format (e.g. +14155552671)
    :param dvar_torah: The דבר תורה reflection text connecting the Parasha to current events
    :param article_url: URL of the source Parasha article, appended to the message
    :return: A confirmation string describing the result
    """
    message_text = build_parasha_message(
        parasha=jewish_events.get("parasha"),
        description=jewish_events.get("description"),
        dvar_torah=dvar_torah,
        article_url=article_url,
    )
    response = send_whatsapp_message(recipient_phone, message_text)
    return f"Message sent successfully: {response}"


def run_agent():
    recipient_phone_number = os.environ.get('RECIPIENT_PHONE_NUMBER')
    if not recipient_phone_number:
        print("No recipient phone number")
        exit(-1)
    result = agent.run_sync()
    print(result.output)
