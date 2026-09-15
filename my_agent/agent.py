import json
import os
from pathlib import Path
from openai import OpenAI
from openai.types.chat import ChatCompletion

from .tools import call_tool, TOOLS_SCHEMA

client = OpenAI(
    base_url=os.environ.get("PROVIDER_URL", "http://localhost:11434/v1"),
    api_key=os.environ.get("OPENAI_API_KEY", "WE_DO_NOT_NEED_API_KEY_LOL"),
)

MODEL = os.environ.get("MODEL", "llama3.2")
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "res" / "system_prompt.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def log_usage_statistics(response: ChatCompletion) -> None:
    if response.usage:
        print(f"Total tokens: {response.usage.total_tokens}. Prompt tokens: {response.usage.prompt_tokens}")


def run_agent() -> None:
    messages_context = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("User: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye master!")
            break

        if user_input in {'/exit', '/bye'}:
            print("Bye master!")
            break

        if not user_input:
            continue

        messages_context.append({"role": "user", "content": user_input})

        response = client.chat.completions.create(
            model=MODEL,
            tools=TOOLS_SCHEMA,
            messages=messages_context,
        )

        message = response.choices[0].message
        messages_context.append(message.model_dump(exclude_none=True))

        while message.tool_calls:
            for tool_call in message.tool_calls:
                tool_result_message = call_tool(tool_call)
                messages_context.append(tool_result_message)

            response = client.chat.completions.create(
                model=MODEL,
                tools=TOOLS_SCHEMA,
                messages=messages_context,
            )
            message = response.choices[0].message
            messages_context.append(message.model_dump(exclude_none=True))

        print(f"Dorina: {message.content}")

        with open('context.json', 'w', encoding='utf-8') as context_json:
            json.dump(messages_context, context_json, indent=2)

        log_usage_statistics(response)


if __name__ == "__main__":
    run_agent()
