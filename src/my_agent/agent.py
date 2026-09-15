import json
import os
from pathlib import Path
from google import genai
from google.genai import types

from .tools import TOOLS_LIST

client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
)

MODEL = os.environ.get("MODEL", "gemini-3.6-flash")
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "res" / "system_prompt.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def run_agent() -> None:
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=TOOLS_LIST,
        temperature=0.2,
    )

    chat = client.chats.create(
        model=MODEL,
        config=config,
    )

    while True:
        try:
            user_input = input("User: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye master!")
            break

        if user_input in {"/exit", "/bye"}:
            print("Bye master!")
            break

        if not user_input:
            continue

        response = chat.send_message(user_input)

        print(f"Dorina: {response.text}")

        if response.usage_metadata:
            print(
                f"Total tokens: {response.usage_metadata.total_token_count}. "
                f"Prompt tokens: {response.usage_metadata.prompt_token_count}"
            )


if __name__ == "__main__":
    run_agent()
