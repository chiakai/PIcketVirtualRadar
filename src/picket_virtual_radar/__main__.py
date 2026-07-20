from __future__ import annotations

import logging
import sys

from .app import RadarApplication
from .config import load_config


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    try:
        config = load_config()
        configure_logging(config.runtime.log_level)
    except Exception as error:
        logging.basicConfig(level=logging.ERROR)
        logging.exception("invalid configuration: %s", error)
        return 2
    return RadarApplication(config).run()


if __name__ == "__main__":
    sys.exit(main())
