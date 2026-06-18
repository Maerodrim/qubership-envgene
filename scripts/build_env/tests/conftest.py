import logging

import pytest

logger = logging.getLogger("test")


@pytest.fixture(autouse=True)
def log_test_boundaries(request):
    """Log start and end of every test with its full node id."""
    logger.info("START  %s", request.node.nodeid)
    yield
    outcome = "PASSED"
    if request.node.rep_call.failed if hasattr(request.node, "rep_call") else False:
        outcome = "FAILED"
    logger.info("FINISH %s — %s", request.node.nodeid, outcome)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
