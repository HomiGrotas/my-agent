import os
from pathlib import Path
from openai import OpenAI, ChatCompletion

from .tools import call_tool, TOOLS_SCHEMA

client = OpenAI(
    base_url=os.environ.get("PROVIDER_URL", "http://localhost:11434/v1"),
    api_key='WE_DO_NOT_NEED_API_KEY_LOL'
)

MODEL = os.environ.get("NODEL", "llama3.2")
SYSTEM_PROMPT = (Path(__file__).parent.parent / "res" / "system_prompt.md").read_text()


def log_usage_statistics(response: ChatCompletion):
    print(f"Total tokens: {response.usage.total_tokens}. Prompt tokens: {response.usage.prompt_tokens}")


def run_agent():
    messages_context = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    while True:
        user_input = input("User: ")

        if user_input in {'/exit', '/bye'}:
            print("Bye master!")
            break

        messages_context.append(
            {
                "role": "user",
                "content": user_input
            }
        )
        response = client.chat.completions.create(
            model=MODEL,
            tools=TOOLS_SCHEMA,
            messages=messages_context,
        )

        message = response.choices[0].message

        if message.tool_calls:
            for tool_call in message.tool_calls:
                messages_context.append(call_tool(tool_call))

            response = client.chat.completions.create(
                model=MODEL,
                tools=TOOLS_SCHEMA,
                messages=messages_context,
            )
            message = response.choices[0].message
            print("Dorina After Tool Calling:", message.content)

        else:
            print("Dorina:", message.content)

        log_usage_statistics(response)
