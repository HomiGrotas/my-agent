import json
from typing import Optional


from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall
from .read_file import ReadFileTool
from .write_file import WriteFileTool
from .models import Tool


ALL_TOOLS = {
    ReadFileTool.name: ReadFileTool,
    WriteFileTool.name: WriteFileTool,
}

TOOLS_SCHEMA = [tool.schema for tool in ALL_TOOLS.values()]


def call_tool(function_call: ChatCompletionMessageFunctionToolCall):
    tool: Optional[Tool] = ALL_TOOLS.get(function_call.function.name)
    if tool:
        argv = json.loads(function_call.function.arguments)

        print(f"Calling {function_call.function.name} with args of {argv}")
        result = tool.func(argv)

        print("Result:", result)
        return {
            "role": "tool",
            "tool_call_id": function_call.id,
            "name": tool.name,
            "content": result,
        }
    return f"Error: function {function_call.function.name} does not exist"
