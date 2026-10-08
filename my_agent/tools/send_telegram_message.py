import json
import os
from pathlib import Path

import requests

# Telegram Bot API limit for a single message's text
MAX_MESSAGE_LENGTH = 4096

# Every user who ever messaged the bot, kept across runs (Telegram only keeps updates for ~24h)
DEFAULT_SUBSCRIBERS_FILE = Path(__file__).resolve().parents[2] / "data" / "telegram_subscribers.json"


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


# Private-chat commands that change a user's subscription; any other message subscribes a new user
SUBSCRIBE_COMMANDS = {"/start", "/subscribe"}
UNSUBSCRIBE_COMMANDS = {"/stop", "/unsubscribe"}

SUBSCRIBED_REPLY = "נרשמת לדבר התורה השבועי על פרשת השבוע. להסרה שלחו /stop"
UNSUBSCRIBED_REPLY = "הוסרת מרשימת התפוצה. להרשמה מחדש שלחו /start"


def _get_command(text: str) -> str:
    """Returns the bot command a message starts with (e.g. "/stop@MyBot now" -> "/stop"), or ""."""
    if not text.startswith("/"):
        return ""
    return text.split()[0].split("@")[0].lower()


def get_recent_telegram_events() -> list[tuple[str, str]]:
    """Returns what users did in their private chats with the bot recently, oldest first.

    Telegram keeps pending updates for about 24 hours. Updates are not acknowledged, so repeated
    calls return the same events. Returns an empty list if the updates can't be fetched
    (e.g. when the bot has a webhook set).

    :return: (chat ID, event) pairs; event is "subscribe" (/start), "unsubscribe" (/stop, or the user
        blocked the bot) or "message" (anything else)
    """
    bot_token = _get_credentials()
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        response = requests.get(
            url, params={"allowed_updates": '["message", "edited_message", "my_chat_member"]'}
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    events = []
    for update in response.json().get("result", []):
        if member_update := update.get("my_chat_member"):
            if member_update["chat"].get("type") == "private":
                status = member_update["new_chat_member"]["status"]
                event = "unsubscribe" if status == "kicked" else "subscribe"
                events.append((str(member_update["chat"]["id"]), event))
            continue
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {})
        if chat.get("type") != "private":
            continue
        command = _get_command(message.get("text", ""))
        if command in UNSUBSCRIBE_COMMANDS:
            event = "unsubscribe"
        elif command in SUBSCRIBE_COMMANDS:
            event = "subscribe"
        else:
            event = "message"
        events.append((str(chat["id"]), event))
    return events


def _get_subscribers_file() -> Path:
    return Path(os.environ.get("TELEGRAM_SUBSCRIBERS_FILE") or DEFAULT_SUBSCRIBERS_FILE)


def load_telegram_subscribers() -> dict[str, list[str]]:
    """Returns the stored Telegram subscription state (empty lists if nothing is stored yet).

    :return: {"subscribers": chat IDs to send to, "unsubscribed": chat IDs that asked not to get messages}
    """
    subscribers_file = _get_subscribers_file()
    state = json.loads(subscribers_file.read_text()) if subscribers_file.exists() else {}
    if isinstance(state, list):  # Older files hold only the subscribers list
        state = {"subscribers": state}
    return {
        "subscribers": [str(chat_id) for chat_id in state.get("subscribers", [])],
        "unsubscribed": [str(chat_id) for chat_id in state.get("unsubscribed", [])],
    }


def _save_telegram_subscribers(state: dict[str, list[str]]):
    subscribers_file = _get_subscribers_file()
    subscribers_file.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash mid-write can't wipe the stored subscribers
    tmp_file = subscribers_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(state, indent=2))
    tmp_file.replace(subscribers_file)


def update_telegram_subscribers() -> dict[str, list[str]]:
    """Applies the recent bot messages to the stored subscribers, saves them, and confirms changes to users.

    A new user who messages the bot is subscribed; /stop (or blocking the bot) unsubscribes, and an
    unsubscribed user is subscribed again only by /start. Each user whose subscription changed since the
    last run gets a confirmation reply (failures to reply are ignored).

    :return: The updated state, as returned by `load_telegram_subscribers`
    """
    state = load_telegram_subscribers()
    subscribers, unsubscribed = state["subscribers"], state["unsubscribed"]
    was_subscribed = set(subscribers)
    touched = []  # chat IDs whose subscription may have changed
    # Updates are re-read until Telegram drops them (~24h), so replaying old ones must be harmless
    for chat_id, event in get_recent_telegram_events():
        if event == "unsubscribe" and chat_id not in unsubscribed:
            if chat_id in subscribers:
                subscribers.remove(chat_id)
            unsubscribed.append(chat_id)
            touched.append(chat_id)
        elif (event == "subscribe" or (event == "message" and chat_id not in unsubscribed)) \
                and chat_id not in subscribers:
            if chat_id in unsubscribed:
                unsubscribed.remove(chat_id)
            subscribers.append(chat_id)
            touched.append(chat_id)
    changed = [
        chat_id for chat_id in dict.fromkeys(touched)
        if (chat_id in subscribers) != (chat_id in was_subscribed)
    ]
    if touched:
        _save_telegram_subscribers(state)
    for chat_id in changed:
        try:
            send_telegram_message(chat_id, SUBSCRIBED_REPLY if chat_id in subscribers else UNSUBSCRIBED_REPLY)
        except requests.RequestException:
            pass  # e.g. the user blocked the bot
    return state


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
