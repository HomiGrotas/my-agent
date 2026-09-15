from pathlib import Path
from typing import Any, Dict

from .models import Tool

# Maximum file size allowed to prevent overwhelming context window (500 KB default)
MAX_FILE_SIZE_BYTES = 500 * 1024

schema = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read text content from a local file within the current working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the local file to read."
                },
            },
            "required": ["path"]
        }
    }
}


def read_file(argv: Dict[str, Any]) -> str:
    raw_path = argv.get("path")
    if not raw_path:
        return "Error: 'path' parameter wasn't specified."

    try:
        base_dir = Path.cwd().resolve()
        target_path = (base_dir / raw_path).resolve()

        if not target_path.is_relative_to(base_dir):
            return f"Error: Access denied. Path '{raw_path}' points outside working directory."

        if not target_path.exists():
            return f"Error: File '{raw_path}' does not exist."

        if target_path.is_dir():
            return f"Error: Path '{raw_path}' is a directory, not a file."

        file_size = target_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            return (
                f"Error: File '{raw_path}' is too large to read ({file_size} bytes. "
                f"Max allowed file size is {MAX_FILE_SIZE_BYTES} bytes"
            )

        return target_path.read_text(encoding="utf-8", errors="replace")

    except Exception as error:
        return f"Error reading file '{raw_path}': {error}"


ReadFileTool = Tool(
    name="read_file",
    func=read_file,
    schema=schema,
)
