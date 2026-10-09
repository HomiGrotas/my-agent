import json
import shutil
import subprocess
from pathlib import Path

# Node script that sends the messages through whatsapp-web.js
SENDER_SCRIPT = Path(__file__).resolve().parents[2] / "whatsapp" / "send.js"
# Starting WhatsApp Web takes a while, and a first-time login waits for a QR code scan
TIMEOUT_SECONDS = 10 * 60


def send_whatsapp_messages(recipients: list[str], message_text: str) -> dict[str, str | None]:
    """Sends a WhatsApp text message to several phone numbers and/or groups via whatsapp-web.js.

    All recipients share a single WhatsApp Web session, which must have been linked beforehand
    with `node whatsapp/send.js --login`.

    :param recipients: Recipients' phone numbers in international format, or group chat IDs (`<id>@g.us`,
        listed by `node whatsapp/send.js --list-groups`)
    :param message_text: The message body text to send, in WhatsApp formatting
    :return: Each recipient mapped to None if the message was sent, or to an error message
    """
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required to send WhatsApp messages, but `node` was not found")
    if not (SENDER_SCRIPT.parent / "node_modules").is_dir():
        raise ValueError(f"WhatsApp sender dependencies are missing - run `npm install` in {SENDER_SCRIPT.parent}")

    # stderr is inherited, so the sender's logs (and a QR code, if login is needed) show up in the terminal
    process = subprocess.run(
        [node, str(SENDER_SCRIPT)],
        input=json.dumps({"recipients": recipients, "message": message_text}),
        stdout=subprocess.PIPE,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if process.returncode != 0:
        raise RuntimeError(f"WhatsApp sender failed with exit code {process.returncode}")
    return json.loads(process.stdout)
