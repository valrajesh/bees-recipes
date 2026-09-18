"""Structured logging configuration for BEES-Recipes."""

import logging
import sys
from app.config import settings


def setup_logger(name: str = "bees_recipes") -> logging.Logger:
    """Configures and returns a logger instance with standardized formatting."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    logger.setLevel(level)
    return logger


logger = setup_logger()
