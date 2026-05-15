from __future__ import annotations

import hashlib
import re
import ssl
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.governor.com.tw"
BOOKING_URL = "https://governor.tixi.com.tw/"
CHAIN = "Governor Cinemas"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="總督數位影城",
    city="台北",
    address="台北市松山區長安東路二段219號1樓",
    source_cinema_id="0001",
)


class GovernorScraper:
    """Scraper for Governor Cinemas.

    Governor publishes current movies and a compact text schedule on each movie
    detail page. Online booking is handled by Tixi, but the brand site carries
    richer movie metadata and readable showtimes.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SITE_BASE_URL), "lxml")
        results: list[ScrapedShowtime] = []
        for detail_url, poster_url in self._current_movie_links(soup):
            detail_soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
            movie = self._parse_movie_detail(detail_soup, detail_url, poster_url)
            schedule_text = self._schedule_text(detail_soup)
            for show_date, start_time in self._parse_schedule(schedule_text):
                key = (
                    f"governor:{movie.source_movie_id or self._movie_key(movie.title)}:"
                    f"{show_date.isoformat()}:{start_time.strftime('%H:%M')}"
                )
                results.append(
                    ScrapedShowtime(
                        cinema=CINEMA,
                        movie=movie,
                        show_date=show_date,
                        start_time=start_time,
                        hall_name=None,
                        format="數位",
                        language=None,
                        booking_url=BOOKING_URL,
                        source="governor",
                        source_showtime_id=key,
                        version_label="數位",
                        auditorium_brand=None,
                        projection_type="數位",
                        audio_language=None,
                        subtitle_language=None,
                        source_payload={
                            "detail_url": detail_url,
                            "schedule_text": schedule_text,
                        },
                    )
                )
        return self._dedupe(results)

    def _current_movie_links(self, soup: BeautifulSoup) -> list[tuple[str, str | None]]:
        links: list[tuple[str, str | None]] = []
        for node in soup.select("#movie_list > div[onclick]"):
            onclick = node.get("onclick") or ""
            match = re.search(r"index\.php\?mid=(?P<id>\d+)", onclick)
            if not match:
                continue
            detail_url = urljoin(SITE_BASE_URL, f"index.php?mid={match.group('id')}")
            image = node.select_one("img[src]")
            poster_url = urljoin(SITE_BASE_URL, image.get("src") or "") if image else None
            links.append((detail_url, poster_url))
        return links

    def _parse_movie_detail(
        self,
        soup: BeautifulSoup,
        detail_url: str,
        fallback_poster_url: str | None,
    ) -> ScrapedMovie:
        title = self._detail_title(soup) or self._poster_title(soup) or "總督影城電影"
        poster_url = self._poster_url(soup, detail_url) or fallback_poster_url
        title_zh, title_en = self._split_title(title, poster_url)
        meta = self._movie_meta(soup)
        source_movie_id = self._source_movie_id(detail_url)
        return ScrapedMovie(
            title=title,
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=poster_url,
            release_date=None,
            duration_minutes=self._parse_duration(meta.get("片長")),
            rating=self._rating(meta.get("級別")) or self._rating_from_image(soup),
            genre=meta.get("類型"),
            description=self._description(soup),
            director=meta.get("導演"),
            cast=meta.get("演員"),
            trailer_url=self._trailer_url(soup, detail_url),
            detail_url=detail_url,
            source_movie_id=source_movie_id,
        )

    def _detail_title(self, soup: BeautifulSoup) -> str | None:
        container = soup.select_one("#b_content")
        if not container:
            return None
        for node in container.find_all("div", recursive=True):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and len(text) <= 120 and "場次時間" not in text:
                style = node.get("style") or ""
                if "font-size: 26px" in style or "color: #a60000" in style:
                    return text
        return None

    def _movie_meta(self, soup: BeautifulSoup) -> dict[str, str]:
        meta: dict[str, str] = {}
        for node in soup.select(".movie_info div"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            match = re.match(r"(?P<key>類型|片長|級別|導演|演員)：\s*(?P<value>.+)", text)
            if match:
                meta[match.group("key")] = match.group("value").strip()
        return meta

    def _schedule_text(self, soup: BeautifulSoup) -> str | None:
        marker = soup.find(string=re.compile(r"場次時間"))
        if not marker:
            return None
        table = marker.find_parent("table")
        if not table:
            return None
        cells = table.select("td")
        if len(cells) < 2:
            return None
        return self._clean_text(cells[-1].get_text(" ", strip=True))

    def _parse_schedule(self, value: str | None) -> list[tuple[date, datetime.time]]:
        if not value:
            return []
        normalized = re.sub(r"\s+", "", value)

        showtimes: list[tuple[date, datetime.time]] = []
        for segment in re.finditer(
            r"(?P<date_text>\d{1,2}月\d{1,2}日(?:至(?:\d{1,2}月)?\d{1,2}日)?):"
            r"(?P<times>\d{1,2}:\d{2}(?:[、,]\d{1,2}:\d{2})*)",
            normalized,
        ):
            dates = self._dates_from_text(segment.group("date_text"))
            times = [self._parse_time(item) for item in re.split(r"[、,]", segment.group("times"))]
            for show_date in dates:
                for start_time in times:
                    if start_time:
                        showtimes.append((show_date, start_time))
        return showtimes

    def _dates_from_text(self, value: str) -> list[date]:
        start_match = re.match(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日", value)
        if not start_match:
            return []
        start_date = self._date_for_month_day(
            int(start_match.group("month")),
            int(start_match.group("day")),
        )
        end_match = re.search(r"至(?:(?P<month>\d{1,2})月)?(?P<day>\d{1,2})日", value)
        if not end_match:
            return [start_date]
        end_month = int(end_match.group("month") or start_date.month)
        end_date = self._date_for_month_day(end_month, int(end_match.group("day")))
        if end_date < start_date:
            end_date = end_date.replace(year=end_date.year + 1)
        dates: list[date] = []
        current = start_date
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    def _date_for_month_day(self, month: int, day: int) -> date:
        today = datetime.now(ZoneInfo("Asia/Taipei")).date()
        candidate = date(today.year, month, day)
        if candidate < today - timedelta(days=14):
            candidate = date(today.year + 1, month, day)
        elif candidate > today + timedelta(days=330):
            candidate = date(today.year - 1, month, day)
        return candidate

    def _description(self, soup: BeautifulSoup) -> str | None:
        marker = soup.find(string=re.compile(r"劇情簡介"))
        if not marker:
            return None
        parts: list[str] = []
        for text_node in marker.find_all_next(string=True):
            text = self._clean_text(str(text_node))
            if not text or text == "劇情簡介：":
                continue
            if "總督數位影城" in text or "版權所有" in text:
                break
            parts.append(text)
        return "\n".join(parts).strip() or None

    def _split_title(self, title: str, poster_url: str | None) -> tuple[str | None, str | None]:
        poster_title = self._title_from_poster_url(poster_url)
        if poster_title and title.startswith(poster_title):
            title_en = self._clean_text(title[len(poster_title) :])
            return poster_title, title_en
        match = re.search(r"\s(?P<en>[A-Za-z][A-Za-z0-9 :'’.,!&()/-]+)$", title)
        if match:
            title_en = self._clean_text(match.group("en"))
            title_zh = self._clean_text(title[: match.start()])
            return title_zh, title_en
        return title, None

    def _poster_url(self, soup: BeautifulSoup, detail_url: str) -> str | None:
        node = soup.select_one('#b_content img[src*="movies_img"]')
        return urljoin(detail_url, node.get("src") or "") if node else None

    def _poster_title(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one('#b_content img[src*="movies_img"]')
        return self._title_from_poster_url(node.get("src") if node else None)

    def _title_from_poster_url(self, url: str | None) -> str | None:
        if not url:
            return None
        filename = PurePosixPath(unquote(url)).name
        title = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
        return self._clean_text(title)

    def _rating_from_image(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one('img[src*="class"]')
        if not node:
            return None
        src = node.get("src") or ""
        match = re.search(r"class(?P<class>\d+)", src)
        if not match:
            return None
        return {
            "1": "普遍級",
            "2": "保護級",
            "3": "輔12級",
            "4": "輔15級",
            "5": "限制級",
        }.get(match.group("class"))

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = self._clean_text(value) or ""
        for key, rating in {
            "普": "普遍級",
            "護": "保護級",
            "輔12": "輔12級",
            "輔15": "輔15級",
            "限": "限制級",
        }.items():
            if key in text:
                return rating
        return text or None

    def _parse_duration(self, value: str | None) -> int | None:
        if not value:
            return None
        hour_match = re.search(r"(?P<hours>\d+)\s*小時", value)
        minute_match = re.search(r"(?P<minutes>\d+)\s*分", value)
        hours = int(hour_match.group("hours")) if hour_match else 0
        minutes = int(minute_match.group("minutes")) if minute_match else 0
        total = hours * 60 + minutes
        return total or None

    def _parse_time(self, value: str | None):
        match = re.search(r"\d{1,2}:\d{2}", value or "")
        return datetime.strptime(match.group(0), "%H:%M").time() if match else None

    def _trailer_url(self, soup: BeautifulSoup, detail_url: str) -> str | None:
        iframe = soup.select_one("iframe[src]")
        return urljoin(detail_url, iframe.get("src") or "") if iframe else None

    def _source_movie_id(self, detail_url: str) -> str | None:
        match = re.search(r"[?&]mid=(\d+)", detail_url)
        return match.group(1) if match else None

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

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
        return text or None

    def _movie_key(self, title: str | None) -> str:
        if not title:
            return ""
        return hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
