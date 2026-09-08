"""Shared read-only HTTP client with resilient retry policy."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session():
    session = requests.Session()
    retry = Retry(
        total=3, connect=3, read=3,
        backoff_factor=0.65,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20))
    session.headers.update({"User-Agent": "FantasyCommandCenter/10.1"})
    return session

HTTP = build_session()

def http_json(url, headers=None, timeout=12):
    response = HTTP.get(url, headers=headers or {}, timeout=timeout)
    response.raise_for_status()
    return response.json()

def http_text(url, timeout=15):
    response = HTTP.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content.decode("utf-8-sig", errors="replace")
