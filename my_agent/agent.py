import os

import logfire
from pydantic_ai import Agent, ModelRetry

from my_agent.tools.fetch_israeli_news import fetch_israeli_news
from my_agent.tools.get_parasha_articles import (
    get_parasha_article,
    list_parasha_articles,
    list_rabbis,
)
from my_agent.tools.send_telegram_message import get_recent_telegram_chat_ids, send_telegram_message
from my_agent.tools.send_whatsapp_message import send_whatsapp_message
from my_agent.utils import build_parasha_message, get_coming_jewish_events

logfire.configure(service_name="my-agent")
logfire.instrument_pydantic_ai()

jewish_events = get_coming_jewish_events()

# Each channel's recipients env var (comma-separated); a channel is used whenever it has recipients.
# Telegram also sends to users who messaged the bot in the last ~24h.
CHANNEL_RECIPIENT_ENV_VARS = {
    "whatsapp": "RECIPIENT_PHONE_NUMBER",
    "telegram": "TELEGRAM_CHAT_ID",
}

agent = Agent(
    'google:gemini-3.5-flash-lite',
    instructions=(
        f"You are a Jewish assistant that delivers personalized Parashat HaShavua (weekly Torah portion) messages via WhatsApp and/or Telegram.\n\n"

        f"## Your Workflow\n"
        f"Follow these steps in order:\n"
        f"1. **Gather current news** – Use your tool to fetch Israeli news headlines from the past week."
        f"Use the news in an optimistic way only. Use only articles relevant for the Parasha, no more than 3.\n"
        f"2. **Gather Parasha source material** – Use your tool to list the article previews on the current "
        f"Parasha written by the Rabbi requested by the user, pick the 1-2 articles whose themes best fit "
        f"the news you gathered, then read only those in full and draw on their themes and insights. "
        f"If the user did not name a Rabbi, use \"sacks\" "
        f"(Rabbi Jonathan Sacks' - הרב יונתן זקס \"Covenant & Conversation\").\n"
        f"3. **Write the דבר תורה** – Write a meaningful, insightful reflection that draws a thoughtful, "
        f"relevant connection between the Parasha and one or more current news events, and ends with a "
        f"practical lesson or question for reflection (דבר תורה style). It should be warm, respectful, "
        f"accessible to a general Jewish audience, and concise enough for a text message (under 2500 words). "
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
        f"If a major event is approaching, weave it into the message alongside the Parasha.\n"
        f"If `list_parasha_article_previews` returns an empty list, do NOT write about any other Parasha "
        f"and do not write a דבר תורה — call the send tool with an empty `dvar_torah` and an empty `article_url`."
    ),
)


@agent.tool_plain
def fetch_israeli_news_headlines(query: str = "Israel", max_articles: int = 100) -> list[dict]:
    """Fetch Israeli news headlines from the past week to inform the Parasha message. Using English only

    :param query: Search terms to filter news by (defaults to "Israel")
    :param max_articles: Maximum number of articles to return (defaults to 100)
    :return: A list of recent articles with title, description, source, url and published date
    """
    return fetch_israeli_news(query, max_articles)


@agent.tool_plain
def list_parasha_article_previews(rabbi: str = "sacks") -> list[dict]:
    """List a Rabbi's articles for this week's Parasha as short previews, to choose which ones to read.

    :param rabbi: The Rabbi whose articles to list, as listed by `list_available_rabbis` (e.g. "sacks")
    :return: A list of articles with index, title, a short text preview and published date;
        empty if there are no articles for this week's Parasha
    """
    parasha = jewish_events.get("parasha_en")
    if not parasha:
        return []
    try:
        return list_parasha_articles(parasha, rabbi)
    except ValueError as e:
        raise ModelRetry(str(e)) from e


@agent.tool_plain
def read_parasha_article(index: int, rabbi: str = "sacks") -> dict:
    """Read the full text of one of a Rabbi's articles for this week's Parasha.

    :param index: Index of the article as returned by `list_parasha_article_previews`
    :param rabbi: The Rabbi whose article to read, as listed by `list_available_rabbis` (e.g. "sacks")
    :return: The article with title, full text, url and published date
    """
    try:
        return get_parasha_article(jewish_events.get("parasha_en", ""), rabbi, index)
    except ValueError as e:
        raise ModelRetry(str(e)) from e


@agent.tool_plain
def list_available_rabbis() -> list[str]:
    """List the Rabbis whose Parasha articles can be fetched.

    :return: Rabbi identifiers accepted by `list_parasha_article_previews` and `read_parasha_article`
    """
    return list_rabbis()


def _parse_recipients(value: str | None) -> list[str]:
    """Splits a comma-separated recipients string into a list, dropping empty entries."""
    return [recipient.strip() for recipient in (value or "").split(",") if recipient.strip()]


def _get_recipients() -> dict[str, list[str]]:
    """Returns each channel that has recipients, mapped to its unique recipients."""
    recipients = {
        channel: _parse_recipients(os.environ.get(env_var))
        for channel, env_var in CHANNEL_RECIPIENT_ENV_VARS.items()
    }
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        recipients["telegram"] += get_recent_telegram_chat_ids()
    return {
        channel: list(dict.fromkeys(channel_recipients))
        for channel, channel_recipients in recipients.items()
        if channel_recipients
    }


@agent.tool_plain
def send_parasha_message(dvar_torah: str, article_url: str) -> str:
    """Assemble the Parasha message from its template and send it to the configured recipients.

    :param dvar_torah: The דבר תורה reflection text connecting the Parasha to current events
    :param article_url: URL of the source Parasha article, appended to the message
    :return: A confirmation string describing the result for each recipient
    """
    results = []
    for channel, recipients in _get_recipients().items():
        message_text = build_parasha_message(
            parasha=jewish_events.get("parasha"),
            description=jewish_events.get("description"),
            dvar_torah=dvar_torah,
            article_url=article_url,
            style=channel,
        )
        for recipient in recipients:
            try:
                if channel == "telegram":
                    send_telegram_message(recipient, message_text)
                elif channel == "whatsapp":
                    send_whatsapp_message(recipient, message_text)
                else:
                    raise NotImplementedError(f"Unknown channel '{channel}'")
                results.append(f"{channel} {recipient}: sent")
            except Exception as e:
                results.append(f"{channel} {recipient}: failed: {e}")
    return "\n".join(results)


def run_agent():
    if not _get_recipients():
        print(
            f"No recipient - set at least one of: {', '.join(CHANNEL_RECIPIENT_ENV_VARS.values())}, "
            f"or message the Telegram bot"
        )
        exit(-1)
    rabbi = os.environ.get('RABBI')
    prompt = "Send this week's Parasha message"
    if rabbi:
        prompt += f", based on articles by {rabbi}"
    result = agent.run_sync(prompt)
    print(result.output)
