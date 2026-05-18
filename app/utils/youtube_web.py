from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


YOUTUBE_WEB_SEARCH_URL = "https://www.youtube.com/results"


@dataclass(frozen=True)
class YouTubeWebResult:
    video_id: str
    title: str | None = None
    channel_title: str | None = None


class YouTubeWebSearchError(RuntimeError):
    pass


class YouTubeWebSearchClient:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def first_video(self, query: str) -> YouTubeWebResult | None:
        html = self._fetch_search_html(query)
        renderer = self._first_video_renderer(html)
        if renderer:
            return renderer

        match = re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', html)
        if not match:
            match = re.search(r"/watch\?v=([A-Za-z0-9_-]{11})", html)
        if not match:
            return None
        return YouTubeWebResult(video_id=match.group(1))

    def _fetch_search_html(self, query: str) -> str:
        params = {
            "search_query": query,
            "hl": "zh-TW",
            "gl": "TW",
        }
        request = Request(
            f"{YOUTUBE_WEB_SEARCH_URL}?{urlencode(params)}",
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            raise YouTubeWebSearchError(
                f"YouTube web search returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except URLError as exc:
            raise YouTubeWebSearchError(f"YouTube web search failed: {exc.reason}") from exc

    def _first_video_renderer(self, html: str) -> YouTubeWebResult | None:
        payload = self._yt_initial_data(html)
        if not payload:
            return None

        for renderer in self._walk_video_renderers(payload):
            video_id = renderer.get("videoId")
            if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            return YouTubeWebResult(
                video_id=video_id,
                title=self._title_text(renderer.get("title")),
                channel_title=self._channel_text(renderer),
            )
        return None

    def _yt_initial_data(self, html: str) -> dict | None:
        match = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", html, re.DOTALL)
        if not match:
            match = re.search(r"window\[[\"']ytInitialData[\"']\]\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _walk_video_renderers(self, value):
        if isinstance(value, dict):
            renderer = value.get("videoRenderer")
            if isinstance(renderer, dict):
                yield renderer
            for child in value.values():
                yield from self._walk_video_renderers(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_video_renderers(child)

    def _title_text(self, value) -> str | None:
        if not isinstance(value, dict):
            return None
        if isinstance(value.get("simpleText"), str):
            return value["simpleText"]
        runs = value.get("runs")
        if isinstance(runs, list):
            text = "".join(run.get("text", "") for run in runs if isinstance(run, dict)).strip()
            return text or None
        return None

    def _channel_text(self, renderer: dict) -> str | None:
        owner = renderer.get("ownerText")
        if isinstance(owner, dict):
            text = self._title_text(owner)
            if text:
                return text
        long_byline = renderer.get("longBylineText")
        if isinstance(long_byline, dict):
            return self._title_text(long_byline)
        return None
