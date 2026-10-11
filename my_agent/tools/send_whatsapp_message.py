import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from my_agent.tools.personalization import get_configure_argument, handle_configure
from my_agent.tools.subscriptions import (
    apply_subscription_events,
    load_parasha_message,
    load_subscribers,
    save_parasha_message,
    set_opted_out,
)

# Node script that sends the messages through whatsapp-web.js
SENDER_SCRIPT = Path(__file__).resolve().parents[2] / "whatsapp" / "send.js"
# Starting WhatsApp Web takes a while, and a first-time login waits for a QR code scan
TIMEOUT_SECONDS = 10 * 60

# Private or group messages the bot reacts to (the whole message, case-insensitive). The linked account is a
# regular WhatsApp account, so any other message is left alone (and unread) rather than subscribing its sender.
# Subscribing also sends the latest Parasha message, like /start on Telegram. In a group, a command counts only
# if it tags the linked account ("@<account> הרשמה"; send.js removes the tag), and any member's command applies
# to the whole group (configured by its "<id>@g.us" chat ID). Groups get the weekly message anyway, so there
# "הסרה" opts the group out and "הרשמה" only opts it back in and sends the latest Parasha message.
START_COMMANDS = {"הרשמה", "הירשמות", "start", "subscribe"}
UNSUBSCRIBE_COMMANDS = {"הסרה", "stop", "unsubscribe"}
# Hebrew alias of /configure (a message starting with it sets a personal preference)
CONFIGURE_ALIASES = ("התאמה",)

SUBSCRIBED_REPLY = "נרשמת לדבר התורה השבועי על פרשת השבוע. להסרה שלחו *הסרה*"
UNSUBSCRIBED_REPLY = "הוסרת מרשימת התפוצה. להרשמה מחדש שלחו *הרשמה*"
GROUP_RESUMED_REPLY = "הקבוצה תקבל שוב את דבר התורה השבועי על פרשת השבוע. להסרה תייגו אותי ושלחו *הסרה*"
GROUP_UNSUBSCRIBED_REPLY = "הקבוצה הוסרה מרשימת התפוצה. להרשמה מחדש תייגו אותי ושלחו *הרשמה*"


def _get_node() -> str:
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required for WhatsApp, but `node` was not found")
    if not (SENDER_SCRIPT.parent / "node_modules").is_dir():
        raise ValueError(f"WhatsApp sender dependencies are missing - run `npm install` in {SENDER_SCRIPT.parent}")
    return node


def has_whatsapp_session() -> bool:
    """Returns whether a WhatsApp account was linked (`node whatsapp/send.js --login`) in this session directory."""
    session_dir = os.environ.get("WHATSAPP_SESSION_DIR") or SENDER_SCRIPT.parent / ".wwebjs_auth"
    return Path(session_dir).is_dir()


def normalize_whatsapp_recipient(recipient: str) -> str:
    """Returns a recipient's canonical form: a phone number's digits ("+972 50-..." -> "97250..."), or a chat ID."""
    if recipient.endswith("@c.us"):
        recipient = recipient.removesuffix("@c.us")
    return recipient if "@" in recipient else re.sub(r"\D", "", recipient)


def send_whatsapp_messages(
    recipients: list[str],
    message_text: str,
    messages: dict[str, str] | None = None,
    all_groups: bool = False,
    exclude: list[str] | None = None,
) -> dict[str, str | None]:
    """Sends a WhatsApp text message to several phone numbers and/or groups via whatsapp-web.js.

    All recipients share a single WhatsApp Web session, which must have been linked beforehand
    with `node whatsapp/send.js --login`. It can't run while the WhatsApp bot (`run_whatsapp_bot`)
    uses the same session.

    :param recipients: Recipients' phone numbers in international format, group chat IDs (`<id>@g.us`,
        listed by `node whatsapp/send.js --list-groups`), or users' chat IDs (`<id>@c.us` / `<id>@lid`)
    :param message_text: The message body text to send, in WhatsApp formatting
    :param messages: Texts to send instead of `message_text` to some of the recipients (e.g. personalized ones)
    :param all_groups: Also send to every group the linked account can post in
    :param exclude: Group chat IDs that `all_groups` skips (e.g. groups that unsubscribed)
    :return: Each recipient (including the groups added by `all_groups`) mapped to None if the message was
        sent, or to an error message
    """
    node = _get_node()
    # stderr is inherited, so the sender's logs (and a QR code, if login is needed) show up in the terminal
    process = subprocess.run(
        [node, str(SENDER_SCRIPT)],
        input=json.dumps({
            "recipients": recipients,
            "message": message_text,
            "messages": messages or {},
            "allGroups": all_groups,
            "exclude": exclude or [],
        }),
        stdout=subprocess.PIPE,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if process.returncode != 0:
        raise RuntimeError(f"WhatsApp sender failed with exit code {process.returncode}")
    return json.loads(process.stdout)


def save_whatsapp_parasha_message(message_text: str):
    """Stores the latest Parasha message (WhatsApp formatting), which the bot sends to users who subscribe.

    :param message_text: The full message, as sent to the WhatsApp subscribers
    """
    save_parasha_message("whatsapp", message_text)


def load_whatsapp_parasha_message() -> str | None:
    """Returns the latest Parasha message stored by `save_whatsapp_parasha_message`, or None if there's none."""
    return load_parasha_message("whatsapp")


def load_whatsapp_subscribers() -> dict[str, list[str]]:
    """Returns the stored WhatsApp subscription state (empty lists if nothing is stored yet).

    :return: {"subscribers": phone numbers (digits) or chat IDs to send to, "unsubscribed": those that asked
        not to get messages}
    """
    return load_subscribers("whatsapp")


def _get_whatsapp_event(text: str) -> str | None:
    """Returns the bot event a message is ("start" / "unsubscribe"), or None if it isn't for the bot."""
    command = text.strip().strip("*_~.!").lstrip("/").lower()
    if command in START_COMMANDS:
        return "start"
    if command in UNSUBSCRIBE_COMMANDS:
        return "unsubscribe"
    return None


def _handle_group_event(group_id: str, event: str, send_reply):
    """Opts a group out of the weekly message ("unsubscribe") or back in ("start"), replying in the group.

    Groups get the weekly message without subscribing, so "start" only undoes an opt-out, and then sends
    the latest Parasha message like a private "הרשמה".
    """
    opted_out = event == "unsubscribe"
    if set_opted_out("whatsapp", group_id, opted_out):
        send_reply(group_id, GROUP_UNSUBSCRIBED_REPLY if opted_out else GROUP_RESUMED_REPLY)
    if not opted_out and (parasha_message := load_whatsapp_parasha_message()):
        send_reply(group_id, parasha_message)


def run_whatsapp_bot():
    """Handles subscription messages sent to the linked WhatsApp account as they arrive, forever.

    Runs `send.js --bot`, which reports every private and group text message (including unread ones that
    arrived while the bot was down) as a JSON line {"chat", "user", "text"} on stdout (group messages only
    if they tag the linked account, without the tag; "user" is then the group's chat ID, so commands from any
    member apply to the whole group, and "sender" is the member), and takes {"to", "text"}
    (send a message) and {"seen": chat} (mark a chat read) JSON lines on stdin. "הרשמה" subscribes and
    sends the latest Parasha message, "הסרה" unsubscribes (see `apply_subscription_events`; in a group,
    which gets the weekly message anyway, they only opt it back in or out, see `_handle_group_event`), and
    "/configure ..." / "התאמה ..." sets a personal preference (see `handle_configure`); the chat is then
    marked read, so it isn't handled again on the next start. Other messages are ignored.

    :raises RuntimeError: When the WhatsApp client exits (e.g. the session was logged out)
    """
    process = subprocess.Popen(
        [_get_node(), str(SENDER_SCRIPT), "--bot"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def send_command(command: dict):
        process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def stop(signum, frame):
        raise SystemExit(0)

    # On `docker stop`, let the WhatsApp client close the browser cleanly so the session stays usable
    signal.signal(signal.SIGTERM, stop)
    try:
        for line in process.stdout:
            message = json.loads(line)
            user_id = normalize_whatsapp_recipient(message["user"])
            is_group = message["chat"].endswith("@g.us")
            source = f"{user_id} (by {message.get('sender')})" if is_group else user_id
            configure_argument = get_configure_argument(message["text"], CONFIGURE_ALIASES)
            if configure_argument is not None:
                print(f"Handling WhatsApp /configure from {source}", flush=True)
                send_command({"to": message["chat"], "text": handle_configure("whatsapp", user_id, configure_argument)})
                send_command({"seen": message["chat"]})
                continue
            event = _get_whatsapp_event(message["text"])
            if not event:
                continue
            print(f"Handling WhatsApp event {event!r} from {source}", flush=True)
            def reply(_, text: str, chat=message["chat"]):
                send_command({"to": chat, "text": text})

            if is_group:
                _handle_group_event(user_id, event, reply)
            else:
                apply_subscription_events("whatsapp", [(user_id, event)], reply, SUBSCRIBED_REPLY, UNSUBSCRIBED_REPLY)
            send_command({"seen": message["chat"]})
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
    print(f"WhatsApp client exited with code {process.returncode}", file=sys.stderr, flush=True)
    raise RuntimeError(f"WhatsApp bot exited with code {process.returncode}")
