import json
import os
import sys
import time
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


# Private-chat commands that change a user's subscription; any other message subscribes a new user.
# /start also sends the user the latest Parasha message.
START_COMMAND = "/start"
SUBSCRIBE_COMMANDS = {START_COMMAND, "/subscribe"}
UNSUBSCRIBE_COMMANDS = {"/stop", "/unsubscribe"}

SUBSCRIBED_REPLY = "נרשמת לדבר התורה השבועי על פרשת השבוע. להסרה שלחו /stop"
UNSUBSCRIBED_REPLY = "הוסרת מרשימת התפוצה. להרשמה מחדש שלחו /start"

# Seconds a getUpdates request waits for new updates before returning empty (long polling)
POLL_TIMEOUT = 50
# Seconds to wait before polling again after a failed getUpdates request
POLL_RETRY_DELAY = 10


def _get_command(text: str) -> str:
    """Returns the bot command a message starts with (e.g. "/stop@MyBot now" -> "/stop"), or ""."""
    if not text.startswith("/"):
        return ""
    return text.split()[0].split("@")[0].lower()


def _get_telegram_updates(offset: int | None = None, timeout: int = 0) -> tuple[list[tuple[str, str]], int | None]:
    """Returns what users did in their private chats with the bot since `offset`, oldest first.

    Fetching with an offset acknowledges every earlier update, so Telegram won't return them again
    (unacknowledged updates are kept for about 24 hours). Fails if the bot has a webhook set, or if
    another process is polling the same bot.

    :param offset: The offset returned by the previous call, or None for all pending updates
    :param timeout: Seconds to wait for an update if there's none yet (0 returns immediately)
    :return: (chat ID, event) pairs, and the offset to pass next time. Event is "start" (/start),
        "subscribe" (/subscribe, or the user unblocked the bot), "unsubscribe" (/stop, or the user
        blocked the bot) or "message" (anything else)
    :raises requests.RequestException: If the updates can't be fetched
    """
    bot_token = _get_credentials()
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    response = requests.get(
        url,
        params={
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": '["message", "edited_message", "my_chat_member"]',
        },
        timeout=timeout + 30,
    )
    response.raise_for_status()
    updates = response.json().get("result", [])
    if updates:
        offset = updates[-1]["update_id"] + 1

    events = []
    for update in updates:
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
        elif command == START_COMMAND and "message" in update:  # not on editing an old /start
            event = "start"
        elif command in SUBSCRIBE_COMMANDS:
            event = "subscribe"
        else:
            event = "message"
        events.append((str(chat["id"]), event))
    return events, offset


def _get_subscribers_file() -> Path:
    return Path(os.environ.get("TELEGRAM_SUBSCRIBERS_FILE") or DEFAULT_SUBSCRIBERS_FILE)


def _get_parasha_message_file() -> Path:
    # Kept next to the subscribers, so it's in the same persistent directory
    return _get_subscribers_file().parent / "telegram_parasha_message.txt"


def _write_atomically(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash mid-write (or a concurrent reader) never sees a partial file
    tmp_file = path.with_suffix(".tmp")
    tmp_file.write_text(text)
    tmp_file.replace(path)


def save_telegram_parasha_message(message_text: str):
    """Stores the latest Parasha message (Telegram HTML), which the bot sends to users who /start it.

    :param message_text: The full message, as sent to the Telegram subscribers
    """
    _write_atomically(_get_parasha_message_file(), message_text)


def load_telegram_parasha_message() -> str | None:
    """Returns the latest Parasha message stored by `save_telegram_parasha_message`, or None if there's none."""
    message_file = _get_parasha_message_file()
    return message_file.read_text() if message_file.exists() else None


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
    _write_atomically(_get_subscribers_file(), json.dumps(state, indent=2))


def _apply_telegram_events(events: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Applies bot events to the stored subscribers, saves them, and replies to the users.

    A new user who messages the bot is subscribed; /stop (or blocking the bot) unsubscribes, and an
    unsubscribed user is subscribed again only by /start or /subscribe. Each user whose subscription
    changed gets a confirmation reply, and each user who sent /start then gets the latest Parasha
    message, if one is stored (failures to reply are ignored).

    :param events: (chat ID, event) pairs, as returned by `_get_telegram_updates`
    :return: The updated state, as returned by `load_telegram_subscribers`
    """
    state = load_telegram_subscribers()
    subscribers, unsubscribed = state["subscribers"], state["unsubscribed"]
    was_subscribed = set(subscribers)
    touched = []  # chat IDs whose subscription may have changed
    # Applying an event again must be harmless, as updates are replayed if the bot crashes before acknowledging them
    for chat_id, event in events:
        if event == "unsubscribe" and chat_id not in unsubscribed:
            if chat_id in subscribers:
                subscribers.remove(chat_id)
            unsubscribed.append(chat_id)
            touched.append(chat_id)
        elif (event in ("start", "subscribe") or (event == "message" and chat_id not in unsubscribed)) \
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
    started = [chat_id for chat_id, event in events if event == "start" and chat_id in subscribers]
    if started and (parasha_message := load_telegram_parasha_message()):
        for chat_id in dict.fromkeys(started):
            try:
                send_telegram_message(chat_id, parasha_message)
            except requests.RequestException:
                pass
    return state


def update_telegram_subscribers() -> dict[str, list[str]]:
    """Applies the pending bot messages once (see `_apply_telegram_events`) and acknowledges them.

    Use `run_telegram_bot` to handle them continuously instead. If the updates can't be fetched (e.g.
    the bot is already running), the stored subscribers are returned unchanged.

    :return: The updated state, as returned by `load_telegram_subscribers`
    """
    try:
        events, offset = _get_telegram_updates()
    except requests.RequestException:
        return load_telegram_subscribers()
    state = _apply_telegram_events(events)
    if events:
        try:
            _get_telegram_updates(offset)  # acknowledges the applied updates
        except requests.RequestException:
            pass  # they'll be applied again next time, which is harmless
    return state


def run_telegram_bot():
    """Handles the bot's messages as they arrive (see `_apply_telegram_events`), forever."""
    offset = None
    while True:
        try:
            events, offset = _get_telegram_updates(offset, timeout=POLL_TIMEOUT)
        except requests.RequestException as e:
            print(f"Failed to get Telegram updates, retrying: {e}", file=sys.stderr, flush=True)
            time.sleep(POLL_RETRY_DELAY)
            continue
        if events:
            print(f"Handling Telegram events: {events}", flush=True)
            _apply_telegram_events(events)


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
