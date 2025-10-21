import logging
import sys
from typing import Optional


class _ColorFormatter(logging.Formatter):
    """Lightweight colored formatter for console readability."""

    COLORS = {
        logging.DEBUG: "\033[36m",   # cyan
        logging.INFO: "\033[32m",    # green
        logging.WARNING: "\033[33m", # yellow
        logging.ERROR: "\033[31m",   # red
        logging.CRITICAL: "\033[35m" # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        message = super().format(record)
        if not color:
            return message
        return f"{color}{message}{self.RESET}"


def configure_logging(level: str = "INFO", *, use_colors: Optional[bool] = None) -> None:
    """Configure application logging for console output.

    Args:
        level: Logging level name, e.g., "INFO", "DEBUG".
        use_colors: Force enable/disable colors; defaults to enabled on TTY.
    """
    if use_colors is None:
        use_colors = sys.stderr.isatty()

    logging.captureWarnings(True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates in repeated runs
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    if use_colors:
        handler.setFormatter(_ColorFormatter(fmt, datefmt=datefmt))
    else:
        handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(handler)


