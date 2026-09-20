import logfire
from pydantic_ai import Agent

from my_agent.tools.fetch_israeli_news import fetch_israeli_news
from my_agent.tools.get_parasha_articles import get_parasha_articles
from my_agent.tools.send_whatsapp_message import send_whatsapp_message
from my_agent.utils import get_coming_jewish_events

logfire.configure(service_name="my-agent")
logfire.instrument_pydantic_ai()

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
        f"3. **Craft the message** – Write a meaningful, insightful message that:\n"
        f"   - Names the Parasha and briefly summarizes its core theme or story\n"
        f"   - Draws a thoughtful, relevant connection to one or more current news events\n"
        f"   - Ends with a practical lesson or question for reflection (דבר תורה style)\n"
        f"   - Is warm, respectful, and accessible to a general Jewish audience\n"
        f"   - Is concise enough for a text message (under 300 words)\n"
        f"   - MUST end with the article link: the exact `url` field of the Parasha article you drew from "
        f"(if you used more than one, use the url of the first/primary one), on its own line\n"
        f"4. **Send the message** – Deliver it to the requested phone number using your send tool. "
        f"Do not send it without the article link included.\n\n"

        f"## Tone & Style\n"
        f"- Hebrew only\n"
        f"- Respectful and inclusive of all Jewish denominations\n"
        f"- Engaging, not preachy\n"

        f"## Jewish Calendar Context\n"
        f"{get_coming_jewish_events()}\n\n"

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
def send_whatsapp(recipient_phone: str, message_text: str) -> str:
    """Send a WhatsApp text message to a phone number.

    :param recipient_phone: Recipient's phone number in international format (e.g. +14155552671)
    :param message_text: The message body text to send
    :return: A confirmation string describing the result
    """
    response = send_whatsapp_message(recipient_phone, message_text)
    return f"Message sent successfully: {response}"


def run_agent():
    print("WhatsApp agent ready. Type your request, or 'exit' to quit.")
    message_history = []
    while True:
        user_input = input("> ").strip()
        if user_input.lower() in {"/exit", "/quit"}:
            break

        result = agent.run_sync(user_input, message_history=message_history)
        print(result.output)
        message_history = result.all_messages()
