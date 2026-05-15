from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from datetime import date, datetime, time
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

BASE_URL = "https://www.luxcinema.com.tw"
WEB_BASE_URL = f"{BASE_URL}/web/"
SHOWTIMES_URL = f"{WEB_BASE_URL}2020.php?type=ShowTimes#type_anchor"
CHAIN = "LUX Cinema"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="樂聲影城",
    city="台北",
    address="台北市萬華區武昌街二段85號",
    source_cinema_id="luxcinema",
)


@dataclass(frozen=True)
class LuxMovieIndex:
    source_movie_id: str
    title_zh: str | None
    title_en: str | None
    poster_url: str | None
    detail_url: str


class LuxCinemaScraper:
    """Scraper for LUX Cinema showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SHOWTIMES_URL), "lxml")
        movie_index = self._movie_index(soup)
        results: list[ScrapedShowtime] = []
        for movie_ref in movie_index:
            detail_soup = BeautifulSoup(self._fetch_text(movie_ref.detail_url), "lxml")
            movie = self._movie_from_detail(detail_soup, movie_ref)
            results.extend(self._showtimes_from_detail(detail_soup, movie, movie_ref.detail_url))
        return self._dedupe(results)

    def _movie_index(self, soup: BeautifulSoup) -> list[LuxMovieIndex]:
        movies: list[LuxMovieIndex] = []
        for anchor in soup.select(".movie_all_list a[href*='2020-movie_item.php']"):
            detail_url = urljoin(WEB_BASE_URL, anchor.get("href") or "")
            source_movie_id = self._source_movie_id(detail_url)
            if not source_movie_id:
                continue
            box = anchor.select_one(".movie_list_box")
            if not box:
                continue
            title_zh = self._clean_title(self._first_text(box, "h1"))
            title_en = self._first_text(box, "h2")
            image = box.select_one("img[src]")
            poster_url = image.get("src") if image else None
            movies.append(
                LuxMovieIndex(
                    source_movie_id=source_movie_id,
                    title_zh=title_zh,
                    title_en=title_en,
                    poster_url=poster_url,
                    detail_url=detail_url,
                )
            )
        return movies

    def _movie_from_detail(self, soup: BeautifulSoup, movie_ref: LuxMovieIndex) -> ScrapedMovie:
        info = soup.select_one(".newmovie_top_inner")
        title_zh = self._first_text(info, "h1") if info else movie_ref.title_zh
        title_en = self._first_text(info, "h3") if info else movie_ref.title_en
        meta = self._detail_meta(info)
        title = title_zh or movie_ref.title_zh or title_en or f"LUX Movie {movie_ref.source_movie_id}"
        return ScrapedMovie(
            title=title,
            title_zh=title_zh or movie_ref.title_zh,
            title_en=title_en or movie_ref.title_en,
            original_title=title_en or movie_ref.title_en,
            poster_url=movie_ref.poster_url,
            release_date=self._parse_date(meta.get("release_date")),
            duration_minutes=self._parse_duration(meta.get("duration")),
            rating=self._rating(meta.get("rating")),
            description=self._description(info),
            director=meta.get("director"),
            cast=meta.get("cast"),
            trailer_url=self._trailer_url(soup, movie_ref.detail_url),
            detail_url=movie_ref.detail_url,
            source_movie_id=movie_ref.source_movie_id,
        )

    def _showtimes_from_detail(
        self,
        soup: BeautifulSoup,
        movie: ScrapedMovie,
        detail_url: str,
    ) -> list[ScrapedShowtime]:
        showtimes: list[ScrapedShowtime] = []
        for day_block in soup.select(".movie_time_out"):
            show_date = self._show_date(day_block)
            if not show_date:
                continue
            for anchor in day_block.select(".time_list a[href]"):
                start_time = self._parse_time(anchor.get_text(" ", strip=True))
                if not start_time:
                    continue
                hall_code = self._hall_code(anchor.get_text(" ", strip=True))
                booking_url = urljoin(WEB_BASE_URL, anchor.get("href") or "")
                session_id = self._query_value(booking_url, "sel_ticket_id")
                source_key = (
                    f"luxcinema:{movie.source_movie_id}:{show_date.isoformat()}:"
                    f"{start_time.strftime('%H:%M')}:{session_id or hall_code or ''}"
                )
                showtimes.append(
                    ScrapedShowtime(
                        cinema=CINEMA,
                        movie=movie,
                        show_date=show_date,
                        start_time=start_time,
                        hall_name=self._hall_name(hall_code),
                        format=self._version_label(movie.title, hall_code),
                        language=self._language(movie.title),
                        booking_url=booking_url,
                        source="luxcinema",
                        source_showtime_id=source_key,
                        version_label=self._version_label(movie.title, hall_code),
                        auditorium_brand=hall_code,
                        projection_type="數位",
                        audio_language=self._language(movie.title),
                        subtitle_language=None,
                        source_payload={
                            "detail_url": detail_url,
                            "sel_ticket_id": session_id,
                            "hall_code": hall_code,
                        },
                    )
                )
        return showtimes

    def _detail_meta(self, info) -> dict[str, str]:
        meta: dict[str, str] = {}
        if not info:
            return meta
        lines = [self._clean_text(node.get_text(" ", strip=True)) for node in info.select("h3")]
        lines = [line for line in lines if line]
        if lines:
            meta["release_date"] = lines[1] if len(lines) > 1 else None
        for line in lines:
            if "長度" in line:
                meta["duration"] = line
            elif "級別" in line:
                meta["rating"] = line
            elif "導演" in line:
                meta["director"] = line.split("|", 1)[-1].strip()
            elif "演員" in line:
                meta["cast"] = line.split("|", 1)[-1].strip()
        return meta

    def _show_date(self, day_block) -> date | None:
        month = self._first_text(day_block, ".month")
        day = self._first_text(day_block, ".day")
        if not month or not day:
            return None
        today = datetime.now(ZoneInfo("Asia/Taipei")).date()
        candidate = date(today.year, int(month), int(day))
        if candidate < today.replace(day=1):
            candidate = date(today.year + 1, int(month), int(day))
        return candidate

    def _description(self, info) -> str | None:
        if not info:
            return None
        node = info.select_one("p")
        return self._clean_text(node.get_text(" ", strip=True)) if node else None

    def _trailer_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        iframe = soup.select_one(".newmovie_top_video iframe[src]")
        if not iframe:
            return None
        src = iframe.get("src") or ""
        return urljoin(base_url, src) if src else None

    def _version_label(self, title: str | None, hall_code: str | None) -> str:
        parts = []
        language = self._language(title)
        if language:
            parts.append(language)
        if hall_code:
            parts.append(hall_code)
        return " ".join(parts) or "數位"

    def _language(self, title: str | None) -> str | None:
        text = title or ""
        if "國語" in text:
            return "國語"
        if "日語" in text:
            return "日語"
        if "英語" in text:
            return "英語"
        return None

    def _hall_code(self, value: str | None) -> str | None:
        match = re.search(r"\|\s*(XL|L)\b", value or "")
        return match.group(1) if match else None

    def _hall_name(self, hall_code: str | None) -> str | None:
        if hall_code == "XL":
            return "XL 800席巨幕廳"
        if hall_code == "L":
            return "L 218席大廳"
        return None

    def _parse_duration(self, value: str | None) -> int | None:
        match = re.search(r"\d+", value or "")
        return int(match.group(0)) if match else None

    def _parse_date(self, value: str | None) -> date | None:
        match = re.search(r"\d{4}/\d{1,2}/\d{1,2}", value or "")
        if not match:
            return None
        try:
            return datetime.strptime(match.group(0), "%Y/%m/%d").date()
        except ValueError:
            return None

    def _parse_time(self, value: str | None) -> time | None:
        match = re.search(r"\d{1,2}:\d{2}", value or "")
        if not match:
            return None
        return datetime.strptime(match.group(0), "%H:%M").time()

    def _rating(self, value: str | None) -> str | None:
        text = (value or "").split("|", 1)[-1].strip()
        if not text:
            return None
        mapping = {
            "普遍級": "普遍級",
            "保護級": "保護級",
            "輔12級": "輔12級",
            "輔15級": "輔15級",
            "輔導級": "輔導級",
            "限制級": "限制級",
        }
        for key, rating in mapping.items():
            if key in text:
                return rating
        return text

    def _query_value(self, url: str, key: str) -> str | None:
        values = parse_qs(urlparse(url).query).get(key)
        return values[0] if values else None

    def _source_movie_id(self, detail_url: str) -> str | None:
        return self._query_value(detail_url, "film_id")

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
        with urlopen(request, timeout=60, context=ssl._create_unverified_context()) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _first_text(self, node, selector: str) -> str | None:
        if not node:
            return None
        found = node.select_one(selector)
        return self._clean_text(found.get_text(" ", strip=True)) if found else None

    def _clean_title(self, value: str | None) -> str | None:
        return self._clean_text(re.sub(r"立即訂票$", "", value or ""))

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
        return text or None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
