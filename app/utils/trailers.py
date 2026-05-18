from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def youtube_video_id(value: str | None) -> str | None:
    if not value:
        return None

    text = value.strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        return _valid_video_id(text)

    if host.endswith("youtu.be"):
        return _valid_video_id(parsed.path.strip("/").split("/", 1)[0])

    query_id = parse_qs(parsed.query).get("v")
    if query_id:
        return _valid_video_id(query_id[0])

    match = re.search(r"/(?:embed|shorts|live)/([^/?#]+)", parsed.path)
    if match:
        return _valid_video_id(match.group(1))

    return None


def youtube_watch_url(video_id: str | None) -> str | None:
    clean_id = _valid_video_id(video_id)
    return f"https://www.youtube.com/watch?v={clean_id}" if clean_id else None


def _valid_video_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"[A-Za-z0-9_-]{11}", value.strip())
    return match.group(0) if match else None
