import os
import requests

# Telegram Bot API limit for a single message's text
MAX_MESSAGE_LENGTH = 4096


def _get_credentials():
    """Helper function to load environment variables."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not bot_token:
        raise ValueError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
    return bot_token


def _split_message(message_text: str) -> list[str]:
    """Splits text into chunks within Telegram's length limit, preferring paragraph boundaries."""
    chunks = []
    current = ""
    for paragraph in message_text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= MAX_MESSAGE_LENGTH:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # A single paragraph longer than the limit is hard-split
        while len(paragraph) > MAX_MESSAGE_LENGTH:
            chunks.append(paragraph[:MAX_MESSAGE_LENGTH])
            paragraph = paragraph[MAX_MESSAGE_LENGTH:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def get_recent_telegram_chat_ids() -> list[str]:
    """Returns the chat IDs of users who privately messaged the bot recently.

    Telegram keeps pending updates for about 24 hours. Updates are not acknowledged, so repeated
    calls return the same users. Returns an empty list if the updates can't be fetched
    (e.g. when the bot has a webhook set).

    :return: Unique private chat IDs, in the order they were first seen
    """
    bot_token = _get_credentials()
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        response = requests.get(url, params={"allowed_updates": '["message", "edited_message"]'})
        response.raise_for_status()
    except requests.RequestException:
        return []

    chat_ids = []
    for update in response.json().get("result", []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {})
        if chat.get("type") == "private":
            chat_ids.append(str(chat["id"]))
    return list(dict.fromkeys(chat_ids))


def send_telegram_message(chat_id: str, message_text: str) -> list[dict]:
    """Sends a Telegram text message (HTML formatted) to a chat via a bot.

    Messages longer than Telegram's limit are sent as several consecutive messages.

    :param chat_id: Recipient's Telegram chat ID (the recipient must have started the bot)
    :param message_text: The message body text to send, in Telegram HTML format
    :return: Response JSON from the Telegram Bot API, one per message sent
    """
    bot_token = _get_credentials()
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    responses = []
    for chunk in _split_message(message_text):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": False},
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        responses.append(response.json())
    return responses
