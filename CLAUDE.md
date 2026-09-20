# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hand-rolled AI agent, built with Pydantic AI, that sends a personalized WhatsApp message about the weekly Parashat HaShavua (Torah portion), tying it to current events. `tasks.md` lists in-progress/aspirational goals (RAG over Parashot text, fetching real news, a new system prompt) that are not yet implemented in code — don't assume they exist.

## Commands

This is a `uv`-managed project (`pyproject.toml` + `uv.lock`, `requires-python = ">=3.12"`).

- Install deps: `uv sync`
- Run the agent (interactive CLI loop): `uv run my-agent` or `uv run main.py`
- No test suite, lint config, or CI currently exists in this repo.

## Architecture

- `main.py` — thin entry point, calls `my_agent.run_agent()`.
- `my_agent/agent.py` — defines the single Pydantic AI `Agent` (`google:gemini-3-flash-preview`), its system instructions, tool registration, and the `run_agent()` REPL loop that keeps `message_history` across turns in memory (no persistent storage).
  - The agent's instructions are built at import time and embed the *current* Jewish calendar context (Parasha/holiday/fast) via `get_coming_jewish_events()`, so instructions are effectively regenerated each process start, not per-turn.
  - Tools are registered with `@agent.tool_plain` directly on the module-level `agent` instance (see `send_whatsapp`).
- `my_agent/utils.py` — `get_coming_jewish_events()` calls Sefaria's Calendars API (`https://www.sefaria.org/api/calendars`, `diaspora=0` for the Israel reading) and returns the current week's Parasha (or holiday reading) name and a short description, both in Hebrew.
- `my_agent/tools/` — external-integration tools, exported via `tools/__init__.py`.
  - `send_whatsapp_message.py` wraps the Meta WhatsApp Cloud API (`graph.facebook.com`). Requires env vars `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`; raises `ValueError` if missing.
  - `fetch_israeli_news.py` wraps the NewsAPI.org `/v2/everything` endpoint to fetch Israel-related articles from the past 7 days. Requires env var `NEWS_API_KEY`; raises `ValueError` if missing.
- Observability: `logfire.configure(service_name="my-agent")` + `logfire.instrument_pydantic_ai()` in `agent.py` sends traces to Logfire; credentials live in `.logfire/logfire_credentials.json` (local, not for use as a source of secrets to commit).
- `res/system_prompt.md` is a reference/legacy system prompt not currently loaded by `agent.py`, whose instructions are inlined in code instead.

## Notes for making changes

- When adding new capabilities, follow the existing pattern: implement the integration under `my_agent/tools/`, export it from `tools/__init__.py`, then register it on `agent` in `agent.py` via `@agent.tool_plain` (or `@agent.tool` if it needs run context).
- Required credentials (Gemini API key, WhatsApp tokens) are expected via environment variables, not hardcoded.
