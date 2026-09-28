def upstream_url(base: str, path: str) -> str:
    """Build a full upstream URL from a base URL and a path segment.

    Normalises trailing/leading slashes so callers don't need to.

    Examples:
        upstream_url("http://iam:8001",  "/register") -> "http://iam:8001/register"
        upstream_url("http://iam:8001/", "/register") -> "http://iam:8001/register"
        upstream_url("http://iam:8001",   "register") -> "http://iam:8001/register"
    """
    return base.rstrip("/") + "/" + path.lstrip("/")
