from pathlib import Path
from typing import Any, Dict

from .models import Tool

schema = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write text content to a local file within the current working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the local file to write to."
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write into the file."
                },
            },
            "required": ["path", "content"],
        }
    }
}


def write_file(argv: Dict[str, Any]) -> str:
    raw_path = argv.get("path")
    content = argv.get("content")

    if not raw_path:
        return "Error: 'path' parameter wasn't specified."
    if content is None:
        return "Error: 'content' parameter wasn't specified."

    try:
        base_dir = Path.cwd().resolve()
        target_path = (base_dir / raw_path).resolve()

        if not target_path.is_relative_to(base_dir):
            return f"Error: Access denied. Path '{raw_path}' points outside working directory."

        target_path.parent.mkdir(parents=True, exist_ok=True)

        bytes_written = target_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {bytes_written} bytes to {raw_path}."

    except Exception as error:
        return f"Error writing file '{raw_path}': {error}"


WriteFileTool = Tool(
    name="write_file",
    func=write_file,
    schema=schema,
)