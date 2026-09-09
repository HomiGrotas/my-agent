from pathlib import Path

from .models import Tool

schema = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a local file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the local file"
                },
            },
            "required": ["path"]
        }
    }
}


def read_file(argv: dict):
    path = argv.get('path')
    if not path:
        return "Error: path wasn't specified"  # todo: custom exceptions
    try:
        return (Path.cwd() / path).read_text()
    except Exception as error:
        return f"Error: {error} for path of {path}"


ReadFileTool = Tool(
    name="read_file",
    func=read_file,
    schema=schema,
)
