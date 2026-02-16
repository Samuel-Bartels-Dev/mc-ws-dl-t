import logging
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    # Reconfigure logger on each run to prevent duplicate handlers across repeated executions.
    logger = logging.getLogger("mc_ws_dl_t")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    # Shared formatter keeps console and optional file logs aligned.
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        # Create folder structure automatically so callers can pass a fresh path.
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
