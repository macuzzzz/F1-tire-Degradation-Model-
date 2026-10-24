"""Shared pytest hooks for the tests in tests/ and the doctests in src/ (CHALLENGES.md C20).

pytest records the absolute path of the file that raised a skip. For doctests
marked +SKIP that is a file inside .venv, so reports/test_report.html would
contain the local user name. This hook keeps only the part after
"site-packages" before the report is written.
"""

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    # A skip's longrepr is the tuple (path, line number, reason).
    if report.skipped and isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        path, line, reason = report.longrepr
        text = str(path).replace("\\", "/")
        if "/site-packages/" in text:
            report.longrepr = (text.split("/site-packages/")[-1], line, reason)
