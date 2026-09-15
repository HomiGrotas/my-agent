from pathlib import Path

MAX_FILE_SIZE_BYTES = 500 * 1024


def read_file(path: str) -> str:
    try:
        base_dir = Path.cwd().resolve()
        target_path = (base_dir / path).resolve()

        if not target_path.is_relative_to(base_dir):
            return f"Error: Access denied. Path '{path}' points outside working directory."

        if not target_path.exists():
            return f"Error: File '{path}' does not exist."

        if target_path.is_dir():
            return f"Error: Path '{path}' is a directory, not a file."

        file_size = target_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            return f"Error: File '{path}' is too large ({file_size / 1024:.1f} KB)."

        return target_path.read_text(encoding="utf-8", errors="replace")
    except Exception as error:
        return f"Error reading file '{path}': {error}"


def write_file(path: str, content: str) -> str:
    try:
        base_dir = Path.cwd().resolve()
        target_path = (base_dir / path).resolve()

        if not target_path.is_relative_to(base_dir):
            return f"Error: Access denied. Path '{path}' points outside working directory."

        target_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = target_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {bytes_written} bytes to {path}."
    except Exception as error:
        return f"Error writing file '{path}': {error}"


TOOLS_LIST = [read_file, write_file]
