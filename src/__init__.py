"""This module contains the main code for the package and initializes the logger settings."""
from src.rag.audit import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
logger.info("Logging initialized for package.")
