"""Logger centralizado com níveis coloridos no terminal."""
import logging
import os
import config

COLORS = {
    "DEBUG"   : "\033[36m",
    "INFO"    : "\033[32m",
    "WARNING" : "\033[33m",
    "ERROR"   : "\033[31m",
    "CRITICAL": "\033[35m",
    "RESET"   : "\033[0m"
}

class ColorFormatter(logging.Formatter):
    def format(self, record):
        color  = COLORS.get(record.levelname, COLORS["RESET"])
        reset  = COLORS["RESET"]
        record.levelname = f"{color}{record.levelname:<8}{reset}"
        return super().format(record)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # Handler: terminal colorido
    ch = logging.StreamHandler()
    ch.setFormatter(ColorFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)-14s | %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    # Handler: arquivo
    os.makedirs("logs", exist_ok=True)
    fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-14s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)
    return logger