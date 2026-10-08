# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hand-rolled AI agent, built with Pydantic AI, that sends a personalized WhatsApp and/or Telegram message about the weekly Parashat HaShavua (Torah portion), tying it to current Israeli news and grounding it in articles by a chosen Rabbi. `tasks.md` lists aspirational goals (RAG/embeddings over Parashot text, scraping news websites, a new system prompt) that are not yet implemented — don't assume they exist.

## Commands

This is a `uv`-managed project (`pyproject.toml` + `uv.lock`, `requires-python = ">=3.12"`).

- Install deps: `uv sync`
- Run the agent: `uv run my-agent` or `uv run main.py`
- Refresh a Rabbi's local articles: `uv run scripts/fetch_<rabbi>_articles.py` (run as a script so sibling imports between scripts resolve, e.g. the Chabad script imports Parasha names from `fetch_sivan_rahav_meir_articles.py`)
- No test suite, lint config, or CI currently exists in this repo.

## Runtime configuration (env vars)

- Delivery channels are enabled by having recipients (`_get_recipients()` / `CHANNEL_RECIPIENT_ENV_VARS` in `agent.py`); recipient env vars are comma-separated lists, the message goes to every recipient of every enabled channel (a failure for one recipient doesn't stop the others), and `run_agent()` exits if there are none.
- `RECIPIENT_PHONE_NUMBER` — comma-separated WhatsApp recipients, international format; enables WhatsApp.
- `RABBI` (optional) — Rabbi to base the message on; the agent defaults to `sacks`.
- `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` — Meta WhatsApp Cloud API.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram Bot API; `TELEGRAM_CHAT_ID` is a comma-separated list of chat IDs (recipients must have started the bot). Telegram recipients are merged (deduplicated) with every user who privately messaged the bot in the last ~24h (`get_recent_telegram_chat_ids()` via `getUpdates`, unacknowledged; returns nothing if the bot has a webhook set) — so anyone messaging the bot joins that run's broadcast.
- `NEWS_API_KEY` — NewsAPI.org.
- Gemini API key for the `google:` model provider.

## Architecture

- `main.py` — thin entry point, calls `my_agent.run_agent()`.
- `my_agent/agent.py` — defines the single Pydantic AI `Agent` (`google:gemini-3.5-flash-lite`), its instructions, and tools.
  - `run_agent()` is a **single non-interactive run**: it builds a prompt from `RABBI` (recipients are read from env by the send tool, not passed through the LLM) and calls `agent.run_sync()` once (no REPL, no message history).
  - Instructions are built at import time and embed the current Parasha context from `get_coming_jewish_events()`, so they're fixed per process start. They tell the model to: fetch news → list article previews for the Rabbi → read only the 1–2 best-fitting articles in full → write a Hebrew דבר תורה body only → send it with the source article's `url`.
  - Registered tools (`@agent.tool_plain`): `fetch_israeli_news_headlines`, `list_parasha_article_previews`, `read_parasha_article`, `list_available_rabbis`, `send_parasha_message`. Article tools convert `ValueError` into `ModelRetry` so the model can correct bad Rabbi names / indexes.
  - `send_parasha_message(dvar_torah, article_url)` does not send raw LLM text: for each enabled channel it assembles the final message via `build_parasha_message(style=channel)` (Parasha name, Hebrew description, the LLM's דבר תורה, article URL) and sends it; a failure on one channel is reported but doesn't stop the others.
- `my_agent/utils.py`
  - `get_coming_jewish_events()` — calls Sefaria's Calendars API (`diaspora=0`, Israel reading) and returns `{"parasha", "description"}` in Hebrew (or `{}` if not found).
  - `build_parasha_message()` — the fixed message template (URL on the last line); `style="whatsapp"` uses `*bold*` headers, `style="telegram"` uses `<b>` headers and HTML-escapes all parts.
- `my_agent/tools/` — integrations, exported via `tools/__init__.py`.
  - `send_whatsapp_message.py` — Meta WhatsApp Cloud API (`graph.facebook.com`), sends with `preview_url: True`; raises `ValueError` if credentials are missing.
  - `send_telegram_message.py` — Telegram Bot API `sendMessage` with `parse_mode: HTML`; splits text over 4096 chars into several messages on paragraph boundaries; raises `ValueError` if `TELEGRAM_BOT_TOKEN` is missing. `get_recent_telegram_chat_ids()` returns private chat IDs from `getUpdates`.
  - `fetch_israeli_news.py` — NewsAPI.org `/v2/everything`, Israel-related articles from the past 7 days (paginated up to `max_articles`); raises `ValueError` if `NEWS_API_KEY` is missing.
  - `get_parasha_articles.py` — reads **local** JSON only (no network): `list_rabbis()`, `list_parasha_articles()` (index/title/400-char preview/date), `get_parasha_article()` (full article by index). Rabbi names are normalized and a unique partial match is accepted (e.g. "Rabbi Shlomo Riskin" → `riskin`).
- Article data: `res/parashot_articles/<rabbi>/<parasha-slug>.json` (slug = lowercase, hyphenated English transliteration, e.g. `chayei-sara.json`), each `{"parasha", "articles": [{title, text, url, published_at}]}`. A Rabbi is "available" simply by having a subdirectory. Holiday readings (Sefaria's "Sukkot I", "Pesach Shabbat Chol haMoed", …) map by prefix to holiday files like `sukkot.json` (`HOLIDAY_READING_SLUGS`); currently `sivan_rahav_meir` and `sacks` have them (the Sacks scraper fetches only those five holidays, from the site's `rs_festival` taxonomy). Currently: `chabad`, `rav_kook`, `riskin`, `sacks`, `sivan_rahav_meir`.
- `scripts/fetch_*_articles.py` — scrapers that populate `res/parashot_articles/`. Note: `fetch_chabad_articles.py` writes to `res/parashot_articles_chabad/` (move into `parashot_articles/chabad/` to use), and uses `curl_cffi` to get past Cloudflare; `fetch_gur_galon_articles.py` exists but its output dir isn't populated yet.
- **Both `scripts/` and `res/parashot_articles/` are gitignored** — the article corpus and scrapers are local-only; a fresh clone has no articles until the scripts are run.
- Observability: `logfire.configure(service_name="my-agent")` + `logfire.instrument_pydantic_ai()` in `agent.py`; credentials live in `.logfire/logfire_credentials.json` (local, never commit).
- `res/system_prompt.md` is a legacy reference prompt, not loaded by `agent.py`.

## Notes for making changes

- New capabilities: implement the integration under `my_agent/tools/`, export it from `tools/__init__.py`, then register a thin wrapper on `agent` in `agent.py` via `@agent.tool_plain` (or `@agent.tool` if it needs run context). Tool docstrings are the model-facing descriptions — keep `:param:`/`:return:` accurate.
- Adding a Rabbi: write a `scripts/fetch_<rabbi>_articles.py` that outputs the JSON shape above into `res/parashot_articles/<rabbi>/`; no agent code changes needed.
- Credentials are provided via environment variables, never hardcoded.
