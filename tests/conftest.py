"""Shared pytest fixtures and options for agent-core tests."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require real backend (e.g. Windows Toast). "
        "By default these are skipped.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test (requires --run-integration to run)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return  # run everything
    skip_integration = pytest.mark.skip(reason="needs --run-integration flag to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
