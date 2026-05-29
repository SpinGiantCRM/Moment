"""Tests for utils/logging.py."""

from __future__ import annotations

import logging

from moment.utils.logging import setup_logging


class TestSetupLogging:
    def test_returns_logger(self) -> None:
        logger = setup_logging(verbose=False)
        assert isinstance(logger, logging.Logger)

    def test_verbose_sets_debug(self) -> None:
        logger = setup_logging(verbose=True)
        assert logger.level == logging.DEBUG

    def test_non_verbose_sets_info(self) -> None:
        logger = setup_logging(verbose=False)
        assert logger.level == logging.INFO

    def test_handlers_configured(self) -> None:
        logger = setup_logging()
        assert len(logger.handlers) >= 2  # file + stream
