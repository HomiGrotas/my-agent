from pydantic_ai import Agent

from my_agent.tools.send_whatsapp_message import send_whatsapp_message

agent = Agent(
    'google:gemini-3-flash-preview',
    instructions=(
        "You're a helpful assistant that can send WhatsApp messages on the user's behalf. "
        "Ask for the recipient's phone number and the message content if they weren't provided, "
        "then use the send_whatsapp_message tool to deliver it. Confirm to the user once it's sent."
    ),
)


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
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        result = agent.run_sync(user_input, message_history=message_history)
        print(result.output)
        message_history = result.all_messages()


run_agent()
