"""WebFetch HTTP 边界工具。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse


MAX_URL_LENGTH = 2000
REDIRECT_STATUS_CODES = {301, 302, 307, 308}
MAX_REDIRECTS = 10


@dataclass(frozen=True)
class NormalizedFetchUrl:
    """表示 WebFetch 校验后的 URL。

    original_url 是模型输入；request_url 是实际请求地址，http 会升级为 https。
    """

    original_url: str
    request_url: str
    hostname: str
    upgraded: bool


def normalize_fetch_url(url: str) -> NormalizedFetchUrl:
    """校验 WebFetch URL，并返回实际请求 URL。"""

    raw_url = url.strip()
    if not raw_url:
        raise ValueError("URL must be a non-empty string")
    if len(raw_url) > MAX_URL_LENGTH:
        raise ValueError(f"URL exceeds maximum length of {MAX_URL_LENGTH}")

    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain credentials")

    hostname = parsed.hostname or ""
    if not _has_public_hostname_shape(hostname):
        raise ValueError("URL must have a valid hostname")

    upgraded = parsed.scheme == "http"
    if upgraded:
        parsed = parsed._replace(scheme="https")

    return NormalizedFetchUrl(
        original_url=raw_url,
        request_url=urlunparse(parsed),
        hostname=hostname,
        upgraded=upgraded,
    )


def _has_public_hostname_shape(hostname: str) -> bool:
    """按 Claude WebFetch 的第一层过滤，拒绝单段或明显无效 hostname。"""

    if "." not in hostname:
        return False
    parts = hostname.split(".")
    if any(not part for part in parts):
        return False
    return len(parts) >= 2


def resolve_redirect_url(original_url: str, location: str) -> str:
    """按 HTTP 规则把相对 redirect location 解析成绝对 URL。"""

    return urljoin(original_url, location)


def is_permitted_redirect(original_url: str, redirect_url: str) -> bool:
    """判断 redirect 是否允许自动跟随。

    与 Claude WebFetch 一致：协议和端口必须不变，目标不能带 credentials，
    hostname 只能是相同 host 或 `www.` 变体。
    """

    try:
        original = urlparse(original_url)
        redirect = urlparse(redirect_url)
    except Exception:
        return False

    if redirect.scheme != original.scheme:
        return False
    if redirect.port != original.port:
        return False
    if redirect.username or redirect.password:
        return False

    def strip_www(hostname: str | None) -> str:
        return (hostname or "").removeprefix("www.")

    return strip_www(original.hostname) == strip_www(redirect.hostname)
