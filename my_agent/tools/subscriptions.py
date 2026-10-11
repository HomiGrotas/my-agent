"""Subscription state shared by the Telegram and WhatsApp bots.

Each channel stores {"subscribers", "unsubscribed"} in `<channel>_subscribers.json`, personal preferences
(set with /configure) in `<channel>_customizations.json`, and the latest Parasha message (in the channel's
formatting, sent to users who subscribe) in `<channel>_parasha_message.txt`, all in the data directory
(`data/`, kept across runs).
"""
import json
import os
from collections.abc import Callable
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Env var overriding where each channel's subscribers file is; its message file is kept next to it
SUBSCRIBERS_FILE_ENV_VARS = {
    "telegram": "TELEGRAM_SUBSCRIBERS_FILE",
    "whatsapp": "WHATSAPP_SUBSCRIBERS_FILE",
}

# Bot events: "start" subscribes and also sends the latest Parasha message, "subscribe" subscribes,
# "unsubscribe" unsubscribes, and "message" (any other message) subscribes only users who never unsubscribed
EVENTS = ("start", "subscribe", "unsubscribe", "message")


def _get_subscribers_file(channel: str) -> Path:
    return Path(os.environ.get(SUBSCRIBERS_FILE_ENV_VARS[channel]) or DATA_DIR / f"{channel}_subscribers.json")


def _get_parasha_message_file(channel: str) -> Path:
    # Kept next to the subscribers, so it's in the same persistent directory
    return _get_subscribers_file(channel).parent / f"{channel}_parasha_message.txt"


def _write_atomically(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash mid-write (or a concurrent reader) never sees a partial file
    tmp_file = path.with_suffix(".tmp")
    tmp_file.write_text(text)
    tmp_file.replace(path)


def save_parasha_message(channel: str, message_text: str):
    """Stores the latest Parasha message, which the channel's bot sends to users who subscribe.

    :param channel: "telegram" or "whatsapp"
    :param message_text: The full message, as sent to the channel's subscribers
    """
    _write_atomically(_get_parasha_message_file(channel), message_text)


def load_parasha_message(channel: str) -> str | None:
    """Returns the latest Parasha message stored by `save_parasha_message`, or None if there's none."""
    message_file = _get_parasha_message_file(channel)
    return message_file.read_text() if message_file.exists() else None


def load_subscribers(channel: str) -> dict[str, list[str]]:
    """Returns the channel's stored subscription state (empty lists if nothing is stored yet).

    :param channel: "telegram" or "whatsapp"
    :return: {"subscribers": user IDs to send to, "unsubscribed": user IDs that asked not to get messages}
    """
    subscribers_file = _get_subscribers_file(channel)
    state = json.loads(subscribers_file.read_text()) if subscribers_file.exists() else {}
    if isinstance(state, list):  # Older files hold only the subscribers list
        state = {"subscribers": state}
    return {
        "subscribers": [str(user_id) for user_id in state.get("subscribers", [])],
        "unsubscribed": [str(user_id) for user_id in state.get("unsubscribed", [])],
    }


def apply_subscription_events(
    channel: str,
    events: list[tuple[str, str]],
    send_reply: Callable[[str, str], None],
    subscribed_reply: str,
    unsubscribed_reply: str,
) -> dict[str, list[str]]:
    """Applies bot events to the channel's stored subscribers, saves them, and replies to the users.

    /stop-like events unsubscribe, and an unsubscribed user is subscribed again only by "start" or
    "subscribe". Each user whose subscription changed gets a confirmation reply, and each subscribed user
    who sent "start" then gets the latest Parasha message, if one is stored. Applying events again is
    harmless, as bots replay unacknowledged events after a crash.

    :param channel: "telegram" or "whatsapp"
    :param events: (user ID, event) pairs, oldest first; event is one of `EVENTS`
    :param send_reply: Sends a text to a user ID; its failures (e.g. the user blocked the bot) are ignored
    :param subscribed_reply: Confirmation sent to a user who was subscribed
    :param unsubscribed_reply: Confirmation sent to a user who was unsubscribed
    :return: The updated state, as returned by `load_subscribers`
    """
    state = load_subscribers(channel)
    subscribers, unsubscribed = state["subscribers"], state["unsubscribed"]
    was_subscribed = set(subscribers)
    touched = []  # user IDs whose subscription may have changed
    for user_id, event in events:
        if event == "unsubscribe" and user_id not in unsubscribed:
            if user_id in subscribers:
                subscribers.remove(user_id)
            unsubscribed.append(user_id)
            touched.append(user_id)
        elif (event in ("start", "subscribe") or (event == "message" and user_id not in unsubscribed)) \
                and user_id not in subscribers:
            if user_id in unsubscribed:
                unsubscribed.remove(user_id)
            subscribers.append(user_id)
            touched.append(user_id)
    if touched:
        _write_atomically(_get_subscribers_file(channel), json.dumps(state, indent=2))

    def reply(user_id: str, text: str):
        try:
            send_reply(user_id, text)
        except Exception:
            pass

    for user_id in dict.fromkeys(touched):
        if (user_id in subscribers) != (user_id in was_subscribed):
            reply(user_id, subscribed_reply if user_id in subscribers else unsubscribed_reply)
    started = [user_id for user_id, event in events if event == "start" and user_id in subscribers]
    if started and (parasha_message := load_parasha_message(channel)):
        for user_id in dict.fromkeys(started):
            reply(user_id, parasha_message)
    return state


def set_opted_out(channel: str, user_id: str, opted_out: bool) -> bool:
    """Opts a recipient that gets messages without subscribing (e.g. a WhatsApp group) out, or back in.

    The recipient is never stored as a subscriber (and removed from the subscribers if it was one), only in
    "unsubscribed" while opted out.

    :param channel: "telegram" or "whatsapp"
    :param user_id: The recipient's ID
    :param opted_out: True to stop sending to it, False to send to it again
    :return: Whether its opt-out status changed
    """
    stored = load_subscribers(channel)
    was_opted_out = user_id in stored["unsubscribed"]
    state = dict(stored)
    state["subscribers"] = [subscriber for subscriber in state["subscribers"] if subscriber != user_id]
    state["unsubscribed"] = [unsubscribed for unsubscribed in state["unsubscribed"] if unsubscribed != user_id]
    if opted_out:
        state["unsubscribed"].append(user_id)
    if state != stored:
        _write_atomically(_get_subscribers_file(channel), json.dumps(state, indent=2))
    return was_opted_out != opted_out


def _get_customizations_file(channel: str) -> Path:
    return _get_subscribers_file(channel).parent / f"{channel}_customizations.json"


def load_customizations(channel: str) -> dict[str, str]:
    """Returns the channel's stored personal preferences (set with /configure), by user ID.

    :param channel: "telegram" or "whatsapp"
    :return: User ID mapped to its preference, as normalized by the configure guard
    """
    customizations_file = _get_customizations_file(channel)
    return json.loads(customizations_file.read_text()) if customizations_file.exists() else {}


def set_customization(channel: str, user_id: str, preference: str | None):
    """Stores a user's personal preference, or deletes it if `preference` is None.

    :param channel: "telegram" or "whatsapp"
    :param user_id: The user's ID, as stored in the channel's subscribers
    :param preference: The normalized preference (never the user's raw text), or None to delete it
    """
    customizations = load_customizations(channel)
    if preference is None:
        customizations.pop(user_id, None)
    else:
        customizations[user_id] = preference
    _write_atomically(_get_customizations_file(channel), json.dumps(customizations, ensure_ascii=False, indent=2))
