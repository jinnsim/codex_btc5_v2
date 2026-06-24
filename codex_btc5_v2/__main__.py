from __future__ import annotations

import argparse
import time

from .config import settings
from .indicators import fetch_snapshot, indicator_text
from .paper import PaperBook
from .runner import format_paper, run, run_paper_round


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC 5m indicator telemetry + paper trading")
    parser.add_argument("command", choices=("once", "run", "paper-once"))
    args = parser.parse_args()
    settings.validate_no_live()
    if args.command == "once":
        print(indicator_text(settings))
    elif args.command == "paper-once":
        settings.validate_paper()
        book = PaperBook(
            settings.paper_ledger_db,
            settings.paper_initial_cash,
            settings.paper_strategy_id,
        )
        snapshot = fetch_snapshot(settings)
        result = run_paper_round(book, snapshot, int(time.time()), settings)
        print(f"paper-once result: {result}")
        print(format_paper(book.summary()))
    else:
        run(settings)


if __name__ == "__main__":
    main()
