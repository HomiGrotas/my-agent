import sys


def run_agent():
    # Imported lazily so lightweight entry points (e.g. collecting Telegram subscribers)
    # don't build the agent, which needs the model API key and fetches the Parasha at import time
    from .agent import run_agent as _run_agent
    _run_agent()


def collect_telegram_subscribers():
    """Stores the users who subscribed to / unsubscribed from the Telegram bot recently, without sending the Parasha."""
    from .tools import update_telegram_subscribers
    subscription = update_telegram_subscribers()
    print(
        f"{len(subscription['subscribers'])} Telegram subscribers, "
        f"{len(subscription['unsubscribed'])} unsubscribed"
    )


def main():
    """Command-line entry point (`my-agent` / `main.py`)."""
    if "--collect-telegram-subscribers" in sys.argv[1:]:
        collect_telegram_subscribers()
    else:
        run_agent()
