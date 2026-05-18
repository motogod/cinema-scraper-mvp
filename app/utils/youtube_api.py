from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


@dataclass(frozen=True)
class YouTubeVideoCandidate:
    video_id: str
    title: str
    channel_title: str
    published_at: str | None


class YouTubeApiError(RuntimeError):
    pass


class YouTubeApiClient:
    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout

    def search_videos(
        self,
        query: str,
        max_results: int = 5,
        region_code: str = "TW",
        relevance_language: str = "zh-Hant",
    ) -> list[YouTubeVideoCandidate]:
        params = {
            "key": self.api_key,
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": str(max_results),
            "regionCode": region_code,
            "relevanceLanguage": relevance_language,
            "safeSearch": "none",
        }
        request = Request(
            f"{YOUTUBE_SEARCH_URL}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "cinema-scraper-mvp/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise YouTubeApiError(_http_error_message(exc)) from exc
        except URLError as exc:
            raise YouTubeApiError(f"YouTube API request failed: {exc.reason}") from exc

        candidates: list[YouTubeVideoCandidate] = []
        for item in payload.get("items", []):
            video_id = ((item.get("id") or {}).get("videoId") or "").strip()
            snippet = item.get("snippet") or {}
            if not video_id:
                continue
            candidates.append(
                YouTubeVideoCandidate(
                    video_id=video_id,
                    title=(snippet.get("title") or "").strip(),
                    channel_title=(snippet.get("channelTitle") or "").strip(),
                    published_at=snippet.get("publishedAt"),
                )
            )
        return candidates


def _http_error_message(exc: HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="ignore")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return f"YouTube API returned HTTP {exc.code}: {exc.reason}"

    error = payload.get("error") or {}
    message = error.get("message") or exc.reason
    details = error.get("errors") or []
    reasons = [
        detail.get("reason")
        for detail in details
        if isinstance(detail, dict) and detail.get("reason")
    ]
    reason_text = f" ({', '.join(reasons)})" if reasons else ""
    return f"YouTube API returned HTTP {exc.code}: {message}{reason_text}"
