"""Offline validation and parsing for Dianping merchant shares."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MAX_SHARE_INPUT_LENGTH = 8_000
MAX_DIANPING_URL_LENGTH = 2_048
MAX_MERCHANT_ID_LENGTH = 128
MAX_NAME_SUGGESTION_LENGTH = 200

_ALLOWED_HOSTS = frozenset({"dianping.com", "www.dianping.com", "m.dianping.com"})
_TRACKING_QUERY_KEYS = frozenset(
    {
        "msource",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
_URL_PATTERN = re.compile(r"https?://[^\s<>\"'\[\]\(\)【】]+", re.IGNORECASE)
_TITLE_PATTERN = re.compile(r"【([^【】\r\n]+)】")
_MERCHANT_ID_PATTERN = re.compile(
    rf"^[A-Za-z0-9][A-Za-z0-9_-]{{0,{MAX_MERCHANT_ID_LENGTH - 1}}}$"
)
_ADDRESS_MARKER_PATTERN = re.compile(
    r"(?:路|街|弄|巷|号|號|楼|樓|室|大厦|大廈|广场|廣場|中心|商场|商場|园|園|坊|里)"
)


class DianpingInputError(ValueError):
    """Raised when a Dianping URL or share text is unsafe or ambiguous."""


@dataclass(frozen=True)
class DianpingParseResult:
    url: str
    name_suggestion: str | None
    address_hint: str | None
    requires_name: bool


def _clean_extracted_url(value: str) -> str:
    """Remove punctuation/Markdown escaping that cannot be part of our URLs."""

    return (
        value.rstrip(".,;:!?，。；：！？")
        .replace(r"\&", "&")
        .replace(r"\_", "_")
    )


def normalize_dianping_url(value: str) -> str:
    """Validate a supported merchant URL and remove known tracking parameters."""

    if not isinstance(value, str):
        raise DianpingInputError("大众点评链接必须是文本。")
    candidate = _clean_extracted_url(value.strip())
    if not candidate:
        raise DianpingInputError("大众点评链接不能为空。")
    if len(candidate) > MAX_DIANPING_URL_LENGTH:
        raise DianpingInputError("大众点评链接过长。")
    if any(character.isspace() for character in candidate):
        raise DianpingInputError("大众点评链接格式错误。")

    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise DianpingInputError("大众点评链接格式错误。") from exc

    if parsed.scheme.lower() != "https":
        raise DianpingInputError("大众点评商户链接必须使用 HTTPS。")
    if parsed.username is not None or parsed.password is not None:
        raise DianpingInputError("大众点评链接不得包含用户名或密码。")
    if port not in (None, 443):
        raise DianpingInputError("大众点评链接端口不受支持。")
    if host not in _ALLOWED_HOSTS:
        raise DianpingInputError("链接不是允许的大众点评域名。")

    path_parts = parsed.path.split("/")
    if len(path_parts) not in (3, 4) or path_parts[0] != "":
        raise DianpingInputError("链接不是支持的大众点评商户路径。")
    if len(path_parts) == 4 and path_parts[3] != "":
        raise DianpingInputError("链接不是支持的大众点评商户路径。")
    route, merchant_id = path_parts[1], path_parts[2]
    if route not in {"shop", "shopshare", "shopinfo"}:
        raise DianpingInputError("链接不是支持的大众点评商户路径。")
    if route == "shopinfo" and host != "m.dianping.com":
        raise DianpingInputError("/shopinfo/ 商户链接只允许使用 m.dianping.com。")
    if not _MERCHANT_ID_PATTERN.fullmatch(merchant_id):
        raise DianpingInputError("大众点评商户 ID 格式无效。")

    retained_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
    ]
    normalized_path = f"/{route}/{merchant_id}"
    normalized_query = urlencode(retained_query, doseq=True)
    return urlunsplit(("https", host, normalized_path, normalized_query, ""))


def _extract_name_suggestion(text: str) -> str | None:
    names = [match.strip() for match in _TITLE_PATTERN.findall(text) if match.strip()]
    unique_names = list(dict.fromkeys(names))
    if len(unique_names) > 1:
        raise DianpingInputError("分享文字包含多个不同的【店铺名称】，无法确定应采用哪一个。")
    if not unique_names:
        return None
    name = unique_names[0]
    if len(name) > MAX_NAME_SUGGESTION_LENGTH:
        raise DianpingInputError("分享文字中的店铺名称过长。")
    return name


def _extract_address_hint(text: str) -> str | None:
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        if not line or "http://" in line.lower() or "https://" in line.lower():
            continue
        if line.startswith("【") and line.endswith("】"):
            continue
        if line.startswith(("★", "☆", "⭐", "¥", "￥")):
            continue
        if _ADDRESS_MARKER_PATTERN.search(line):
            return line[:300]
    return None


def parse_dianping_input(text: str) -> DianpingParseResult:
    """Parse share text or one merchant URL without any network access."""

    if not isinstance(text, str):
        raise DianpingInputError("分享内容必须是文本。")
    value = text.strip()
    if not value:
        raise DianpingInputError("请粘贴大众点评商户链接或完整分享文字。")
    if len(value) > MAX_SHARE_INPUT_LENGTH:
        raise DianpingInputError("分享内容过长，无法安全解析。")

    raw_urls = [_clean_extracted_url(item) for item in _URL_PATTERN.findall(value)]
    if not raw_urls:
        if "dianping.com" in value.casefold():
            raise DianpingInputError("未找到格式正确的 HTTPS 大众点评商户链接。")
        raise DianpingInputError("分享内容中没有大众点评商户链接。")

    normalized_urls = [normalize_dianping_url(item) for item in raw_urls]
    distinct_urls = list(dict.fromkeys(normalized_urls))
    if len(distinct_urls) > 1:
        raise DianpingInputError("分享内容包含多个互相冲突的商户链接。")

    name_suggestion = _extract_name_suggestion(value)
    return DianpingParseResult(
        url=distinct_urls[0],
        name_suggestion=name_suggestion,
        address_hint=_extract_address_hint(value),
        requires_name=name_suggestion is None,
    )
