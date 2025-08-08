"""This module contains the main code for the package and initializes the logger settings."""
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)
logger.info("Logging initialized for package.")
