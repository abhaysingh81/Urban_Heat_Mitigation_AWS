"""Caller address and the CloudFront edge check (Feature M: AWS WAF in front of the API)."""

from __future__ import annotations

import hmac
import os

EDGE_HEADER = "x-origin-verify"


def edge_secret() -> str:
    """Set only when the API is published through CloudFront + WAF. CloudFront adds this value as a
    request header; a request without it reached API Gateway directly and skipped the firewall."""
    return os.environ.get("EDGE_SECRET", "")


def came_through_edge(headers) -> bool:
    secret = edge_secret()
    return bool(secret) and hmac.compare_digest(headers.get(EDGE_HEADER, ""), secret)


def client_ip(request) -> str:
    """Best available caller IP.

    API Gateway appends the address it saw to X-Forwarded-For. Behind CloudFront that address is a
    CloudFront server and the viewer is the entry before it; anything earlier is caller-supplied
    and never trusted."""
    direct = request.client.host if request.client else "unknown"
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if came_through_edge(request.headers) and len(hops) >= 2:
        return hops[-2]
    return direct
