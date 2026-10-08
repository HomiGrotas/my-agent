# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hand-rolled AI agent, built with Pydantic AI, that sends a personalized WhatsApp and/or Telegram message about the weekly Parashat HaShavua (Torah portion), tying it to current Israeli news and grounding it in articles by a chosen Rabbi. `tasks.md` lists aspirational goals (RAG/embeddings over Parashot text, scraping news websites, a new system prompt) that are not yet implemented — don't assume they exist.

## Commands

This is a `uv`-managed project (`pyproject.toml` + `uv.lock`, `requires-python = ">=3.12"`).

- Install deps: `uv sync`
- WhatsApp sender (Node 18+): `cd whatsapp && npm install`, then link an account once with `npm run login` (scan the QR code). In Docker: `docker run -it --rm -v <app>/.wwebjs_auth:/app/whatsapp/.wwebjs_auth my-agent:latest node whatsapp/send.js --login`.
- Run the agent: `uv run my-agent` or `uv run main.py`
- Only apply new Telegram (un)subscriptions (no LLM, no Parasha send): `uv run main.py --collect-telegram-subscribers`
- Deployment (`deploy/`): systemd units running the Docker image — `my-agent.service`/`.timer` sends the message weekly (Fri 08:00 Israel time); `my-agent-subscribers.service`/`.timer` runs the subscriber collection every 12h (02:00/14:00) so no Telegram (un)subscribe is lost to the ~24h `getUpdates` window. `__APP_DIR__` is a placeholder for the app directory on the host.
- Refresh a Rabbi's local articles: `uv run scripts/fetch_<rabbi>_articles.py` (run as a script so sibling imports between scripts resolve, e.g. the Chabad script imports Parasha names from `fetch_sivan_rahav_meir_articles.py`)
- No test suite, lint config, or CI currently exists in this repo.

## Runtime configuration (env vars)

- Delivery channels are enabled by having recipients (`_get_recipients()` / `CHANNEL_RECIPIENT_ENV_VARS` in `agent.py`); recipient env vars are comma-separated lists, the message goes to every recipient of every enabled channel (a failure for one recipient doesn't stop the others), and `run_agent()` exits if there are none.
- `RECIPIENT_PHONE_NUMBER` — comma-separated WhatsApp recipients, international format; enables WhatsApp.
- `RABBI` (optional) — Rabbi to base the message on; the agent defaults to `sacks`.
- `WHATSAPP_SESSION_DIR` (optional) — where whatsapp-web.js keeps the linked WhatsApp session (default `whatsapp/.wwebjs_auth`; `/app/whatsapp/.wwebjs_auth` in Docker, mounted from the host by `deploy/my-agent.service`).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram Bot API; `TELEGRAM_CHAT_ID` is a comma-separated list of chat IDs (recipients must have started the bot). Telegram recipients are merged (deduplicated) with the stored bot subscribers, minus anyone who unsubscribed (also removed from `TELEGRAM_CHAT_ID`). Each run, `update_telegram_subscribers()` replays `getUpdates` (last ~24h, unacknowledged, so replays must be idempotent; nothing if the bot has a webhook set) onto `{"subscribers", "unsubscribed"}`: any private message from a new user subscribes them, `/stop`/`/unsubscribe` or blocking the bot (`my_chat_member` → `kicked`) unsubscribes, and only `/start`/`/subscribe` re-subscribes. Users whose status changed since the last run get a Hebrew confirmation reply.
- `TELEGRAM_SUBSCRIBERS_FILE` (optional) — where those subscriber chat IDs are stored (default `data/telegram_subscribers.json`; in Docker `/app/data` is mounted from the host's `<app>/data` by `deploy/my-agent.service`, so it survives runs). `data/` is gitignored.
- `DEV_MODE` (optional, `1`/`true`/`yes`/`on`) — skips sending to the stored Telegram subscribers (new ones are still recorded), so the message goes only to the recipients configured in the env vars above.
- `NEWS_API_KEY` — NewsAPI.org.
- Gemini API key for the `google:` model provider.

## Architecture

- `main.py` — thin entry point calling `my_agent.main()` (also the `my-agent` script), which runs `run_agent()` or, with `--collect-telegram-subscribers`, only `update_telegram_subscribers()`. `my_agent/__init__.py` imports `agent.py` lazily, so importing `my_agent.tools` doesn't build the agent (which needs the Gemini key and calls Sefaria at import).
- `my_agent/agent.py` — defines the single Pydantic AI `Agent` (`google:gemini-3.5-flash-lite`), its instructions, and tools.
  - `run_agent()` is a **single non-interactive run**: it builds a prompt from `RABBI` (recipients are read from env by the send tool, not passed through the LLM) and calls `agent.run_sync()` once (no REPL, no message history).
  - Instructions are built at import time and embed the current Parasha context from `get_coming_jewish_events()`, so they're fixed per process start. They tell the model to: fetch news → list article previews for the Rabbi → read only the 1–2 best-fitting articles in full → write a Hebrew דבר תורה body only → send it with the source article's `url`.
  - Registered tools (`@agent.tool_plain`): `fetch_israeli_news_headlines`, `list_parasha_article_previews`, `read_parasha_article`, `list_available_rabbis`, `send_parasha_message`. Article tools convert `ValueError` into `ModelRetry` so the model can correct bad Rabbi names / indexes.
  - `send_parasha_message(dvar_torah, article_url)` does not send raw LLM text: for each enabled channel it assembles the final message via `build_parasha_message(style=channel)` (Parasha name, Hebrew description, the LLM's דבר תורה, article URL) and sends it (WhatsApp recipients in one batch, Telegram one by one); a failure on one channel is reported but doesn't stop the others.
- `my_agent/utils.py`
  - `get_coming_jewish_events()` — calls Sefaria's Calendars API (`diaspora=0`, Israel reading) and returns `{"parasha", "description"}` in Hebrew (or `{}` if not found).
  - `build_parasha_message()` — the fixed message template (URL last, except Telegram's trailing "send /stop to unsubscribe" line); `style="whatsapp"` uses `*bold*` headers, `style="telegram"` uses `<b>` headers and HTML-escapes all parts.
- `my_agent/tools/` — integrations, exported via `tools/__init__.py`.
  - `send_whatsapp_message.py` — `send_whatsapp_messages(recipients, text)` runs the Node script `whatsapp/send.js` ([whatsapp-web.js](https://github.com/wwebjs/whatsapp-web.js), headless Chromium) once for all recipients (JSON on stdin, `{recipient: null | error}` on stdout; its stderr logs/QR pass through); raises `ValueError` if `node` or `whatsapp/node_modules` is missing.
  - `send_telegram_message.py` — Telegram Bot API `sendMessage` with `parse_mode: HTML`; splits text over 4096 chars into several messages on paragraph boundaries; raises `ValueError` if `TELEGRAM_BOT_TOKEN` is missing. `get_recent_telegram_events()` returns `(chat_id, "subscribe" | "unsubscribe" | "message")` from `getUpdates`; `load_telegram_subscribers()` / `update_telegram_subscribers()` read / update the stored subscription file (written atomically; an older plain-list file is read as subscribers).
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
