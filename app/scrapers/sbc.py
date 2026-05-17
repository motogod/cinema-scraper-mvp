from __future__ import annotations

import re
import ssl
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.sbcmovies.com.tw"
CINEMA_URL = f"{SITE_BASE_URL}/browsing/Cinemas/Details/1001"
SOURCE = "sbc"
CHAIN = "SBC 星橋國際影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="星橋國際影城",
    city="桃園",
    address="桃園市中壢區中園路二段501號4-7樓",
    source_cinema_id="1001",
)


class SbcScraper:
    """Scraper for SBC Cinema showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(CINEMA_URL), "lxml")
        results: list[ScrapedShowtime] = []
        for item in soup.select(".film-item"):
            movie = self._movie_from_item(item)
            if not movie:
                continue
            format_label = self._format_from_title(item)
            language = self._language_from_title(item)
            for session in item.select("a.session-time"):
                showtime = self._showtime_from_session(
                    session=session,
                    movie=movie,
                    format_label=format_label,
                    language=language,
                )
                if showtime:
                    results.append(showtime)

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("sbc scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_item(self, item) -> ScrapedMovie | None:
        movie_id = self._clean_text(item.get("data-movie-id"))
        raw_title = self._title(item)
        title = self._clean_movie_title(raw_title)
        if not movie_id or not title:
            return None

        detail_url = self._detail_url(item)
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=self._poster_url(item),
            rating=self._rating(item),
            detail_url=detail_url,
            source_movie_id=movie_id,
        )

    def _showtime_from_session(
        self,
        session,
        movie: ScrapedMovie,
        format_label: str | None,
        language: str | None,
    ) -> ScrapedShowtime | None:
        time_node = session.select_one("time[datetime]")
        if not time_node:
            return None
        try:
            starts_at = datetime.fromisoformat(time_node.get("datetime"))
        except (TypeError, ValueError):
            return None

        booking_url = urljoin(SITE_BASE_URL, session.get("href") or "")
        session_id = self._session_id(booking_url)
        source_showtime_id = f"{SOURCE}:{session_id}" if session_id else (
            f"{SOURCE}:{movie.source_movie_id}:{starts_at.strftime('%Y-%m-%dT%H:%M')}"
        )
        version = self._version_label(format_label, language)
        return ScrapedShowtime(
            cinema=CINEMA,
            movie=movie,
            show_date=starts_at.date(),
            start_time=starts_at.time(),
            hall_name=None,
            format=format_label,
            language=language,
            booking_url=booking_url,
            source=SOURCE,
            source_showtime_id=source_showtime_id,
            version_label=version,
            projection_type=format_label,
            audio_language=language,
            subtitle_language="中文字幕" if language and language != "中文" else None,
            source_payload={
                "session_id": session_id,
                "movie_id": movie.source_movie_id,
            },
        )

    def _fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        )
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=60, context=context) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _title(self, item) -> str | None:
        node = item.select_one(".film-title")
        return self._clean_text(node.get_text(" ", strip=True) if node else None)

    def _clean_movie_title(self, title: str | None) -> str | None:
        text = self._clean_text(title)
        if not text:
            return None
        text = re.sub(r"^(?:Chi|Eng)\s*[-:]\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^3D\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])$", "", text)
        return text.strip() or None

    def _format_from_title(self, item) -> str | None:
        title = self._title(item) or ""
        if re.search(r"\b3D\b", title, re.IGNORECASE):
            return "3D"
        return "數位"

    def _language_from_title(self, item) -> str | None:
        title = self._title(item) or ""
        if re.match(r"^\s*Chi\s*[-:]", title, re.IGNORECASE):
            return "中文"
        if re.match(r"^\s*Eng\s*[-:]", title, re.IGNORECASE):
            return "英語"
        return None

    def _poster_url(self, item) -> str | None:
        image = item.select_one(".movie-image img:not(.rating-image)[src]")
        if not image:
            return None
        return urljoin(SITE_BASE_URL, image.get("src"))

    def _rating(self, item) -> str | None:
        image = item.select_one("img.rating-image")
        return self._clean_text(image.get("alt") if image else None)

    def _detail_url(self, item) -> str | None:
        link = item.select_one(".film-header a[href]")
        return urljoin(SITE_BASE_URL, link.get("href")) if link else None

    def _session_id(self, booking_url: str) -> str | None:
        query = parse_qs(urlparse(booking_url).query)
        return (query.get("txtSessionId") or [None])[0]

    def _version_label(self, format_label: str | None, language: str | None) -> str | None:
        values = [value for value in [format_label, language] if value]
        return "/".join(values) if values else None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output

    def _clean_text(self, value) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None
