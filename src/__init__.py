"""This module contains the main code for the package and initializes the logger settings."""
from src.workflows.query.audit import configure_logging, get_logger
import src.settings as settings

configure_logging()
logger = get_logger(__name__)
logger.info("Logging initialized for package.")

__all__ = ["logger", "settings"]
