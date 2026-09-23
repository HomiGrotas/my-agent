import os
import requests

# API Configuration
API_VERSION = "v26.0"


def _get_credentials():
    """Helper function to load environment variables."""
    access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    if not access_token or not phone_number_id:
        raise ValueError(
            "Missing required environment variables: "
            "WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID"
        )
    return access_token, phone_number_id


def send_whatsapp_message(recipient_phone: str, message_text: str) -> dict:
    """Sends a WhatsApp text message to an individual phone number.

    :param recipient_phone: Recipient's phone number
    :param message_text: The message body text to send
    :return: Response JSON from Meta API
    """
    access_token, phone_number_id = _get_credentials()
    url = f"https://graph.facebook.com/{API_VERSION}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "text",
        "text": {"preview_url": True, "body": message_text},
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()
