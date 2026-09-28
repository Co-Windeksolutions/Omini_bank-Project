"""
Unit tests for API Gateway pure utilities.

The Gateway's primary responsibility is HTTP proxying and JWT delegation —
both require live services to test meaningfully. Those are covered by the
Postman/Newman integration test suite that runs in the CI pipeline.

This file covers the one pure utility function (upstream_url) that can be
verified with zero network calls or mocking.
"""

from utils import upstream_url


class TestUpstreamUrl:
    def test_clean_base_and_path(self):
        assert upstream_url("http://iam:8001", "/register") == "http://iam:8001/register"

    def test_trailing_slash_on_base(self):
        assert upstream_url("http://iam:8001/", "/register") == "http://iam:8001/register"

    def test_no_leading_slash_on_path(self):
        assert upstream_url("http://iam:8001", "register") == "http://iam:8001/register"

    def test_both_slashes_present(self):
        assert upstream_url("http://iam:8001/", "/register") == "http://iam:8001/register"

    def test_nested_path(self):
        assert upstream_url("http://wallet:8002", "/transfer") == "http://wallet:8002/transfer"

    def test_empty_path_gives_trailing_slash(self):
        # Edge case: empty path → trailing slash. Not used in practice but must not crash.
        assert upstream_url("http://iam:8001", "") == "http://iam:8001/"
