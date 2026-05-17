from __future__ import annotations

import re
from datetime import date, datetime
from hashlib import sha1
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.t-movies.com.tw/"
SOURCE = "tmovies"
CHAIN = "天台影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="天台影城",
    city="新北",
    address="新北市三重區重新路二段78號4F(天台廣場)",
    source_cinema_id="tmovies-sanchong",
)

RATING_MAP = {
    "C0": "普遍級",
    "C6": "保護級",
    "C12": "輔12級",
    "C15": "輔15級",
    "C18": "限制級",
}
LANGUAGE_MAP = {
    "zh": "中文",
    "de": "德語",
    "en": "英語",
    "es": "西語",
    "fr": "法語",
    "ja": "日語",
    "ko": "韓語",
    "ru": "俄語",
    "th": "泰語",
    "vi": "越語",
    "in": "印語",
    "yu": "粵語",
}


class TMoviesScraper:
    """Scraper for T-Movies Cinema showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SITE_BASE_URL), "lxml")
        results: list[ScrapedShowtime] = []
        for movie_node in soup.select(".section > .movie"):
            movie = self._movie_from_node(movie_node)
            for timelist in movie_node.select(".timelist"):
                show_date = self._show_date(timelist.select_one(".date"))
                if show_date is None:
                    continue
                for item in timelist.select("ol > li"):
                    showtime = self._showtime_from_item(item, movie, show_date)
                    if showtime:
                        results.append(showtime)

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("tmovies scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_node(self, node) -> ScrapedMovie:
        poster_link = node.select_one("a.poster")
        poster = node.select_one("a.poster img")
        title = (
            self._clean_text(poster_link.get("title") if poster_link else None)
            or self._clean_text(poster.get("alt") if poster else None)
            or "T-Movies Movie"
        )
        trailer_url = poster_link.get("href") if poster_link else None
        source_movie_id = self._source_movie_id(node) or self._stable_key(title)
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=urljoin(SITE_BASE_URL, poster.get("src")) if poster and poster.get("src") else None,
            rating=self._rating(node),
            trailer_url=trailer_url if trailer_url and trailer_url.startswith("http") else None,
            detail_url=SITE_BASE_URL,
            source_movie_id=source_movie_id,
        )

    def _showtime_from_item(
        self,
        item,
        movie: ScrapedMovie,
        show_date: date,
    ) -> ScrapedShowtime | None:
        time_text = self._clean_text(item.get_text(" ", strip=True))
        time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", time_text or "")
        if not time_match:
            return None

        link = item.select_one("a[href]")
        booking_url = link.get("href") if link else None
        hall_code = self._hall_code(booking_url) or self._hall_class(item)
        language = self._language(item)
        start_time = datetime.strptime(time_match.group(0), "%H:%M").time()
        source_showtime_id = self._source_showtime_id(
            movie.source_movie_id,
            hall_code,
            show_date,
            time_match.group(0),
            booking_url,
        )
        return ScrapedShowtime(
            cinema=CINEMA,
            movie=movie,
            show_date=show_date,
            start_time=start_time,
            hall_name=self._hall_name(hall_code),
            format="數位",
            language=language,
            booking_url=booking_url,
            source=SOURCE,
            source_showtime_id=source_showtime_id,
            version_label=self._version_label(language),
            projection_type="數位",
            audio_language=language,
            subtitle_language="中文字幕" if language and language != "中文" else None,
            source_payload={
                "booking_url": booking_url,
                "hall_code": hall_code,
                "language_class": self._language_class(item),
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
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _show_date(self, node) -> date | None:
        text = self._clean_text(node.get_text(" ", strip=True) if node else None)
        match = re.search(r"(\d{1,2})月(\d{1,2})日", text or "")
        if not match:
            return None
        now = date.today()
        month = int(match.group(1))
        day = int(match.group(2))
        year = now.year + 1 if now.month == 12 and month == 1 else now.year
        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _source_movie_id(self, node) -> str | None:
        link = node.select_one(".schedule a[href*='/Booking/Buy01_Seat/']")
        if not link:
            return None
        parts = link.get("href", "").rstrip("/").split("/")
        return parts[7] if len(parts) > 7 else None

    def _hall_code(self, booking_url: str | None) -> str | None:
        if not booking_url:
            return None
        parts = booking_url.rstrip("/").split("/")
        return parts[8] if len(parts) > 8 else None

    def _hall_class(self, item) -> str | None:
        for span in item.select("span[class]"):
            classes = span.get("class") or []
            for class_name in classes:
                match = re.fullmatch(r"t(\d+)", class_name)
                if match:
                    return match.group(1).zfill(3)
        return None

    def _hall_name(self, hall_code: str | None) -> str | None:
        if not hall_code:
            return None
        try:
            return f"{int(hall_code)}廳"
        except ValueError:
            return hall_code

    def _language(self, item) -> str | None:
        language_class = self._language_class(item)
        return LANGUAGE_MAP.get(language_class) if language_class else None

    def _language_class(self, item) -> str | None:
        for span in item.select("span[class]"):
            for class_name in span.get("class") or []:
                if class_name in LANGUAGE_MAP:
                    return class_name
        return None

    def _rating(self, node) -> str | None:
        rating_node = node.select_one(".mtitle div[class]")
        if not rating_node:
            return None
        for class_name in rating_node.get("class") or []:
            if class_name in RATING_MAP:
                return RATING_MAP[class_name]
        return None

    def _version_label(self, language: str | None) -> str:
        return f"數位/{language}" if language else "數位"

    def _source_showtime_id(
        self,
        source_movie_id: str | None,
        hall_code: str | None,
        show_date: date,
        time_text: str,
        booking_url: str | None,
    ) -> str:
        if booking_url:
            parts = booking_url.rstrip("/").split("/")
            if len(parts) >= 10:
                return f"{SOURCE}:{':'.join(parts[-4:])}"
        key = f"{source_movie_id}|{hall_code}|{show_date.isoformat()}|{time_text}"
        return f"{SOURCE}:{self._stable_key(key)}"

    def _stable_key(self, value: str | None) -> str:
        return sha1((value or "").encode("utf-8")).hexdigest()[:16]

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
