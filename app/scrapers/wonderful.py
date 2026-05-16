from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://wonderful.movie.com.tw"
BOOKING_URL = "https://www.ezding.com.tw/cinemabooking?cinemaid=f644412efbb811e58858f2128151146f"
CHAIN = "Wonderful Theatre"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="真善美劇院",
    city="台北",
    address="台北市萬華區漢中街116號7樓",
    source_cinema_id="wonderful-taipei",
)


class WonderfulScraper:
    """Scraper for Wonderful Theatre.

    The schedule page lists active movie ids, while each lightbox page contains
    that movie's complete upcoming schedule grouped by date.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        time_html = self._fetch_text(f"{SITE_BASE_URL}/time")
        time_soup = BeautifulSoup(time_html, "lxml")
        available_dates = self._available_dates(time_soup)
        date_by_month_day = {(value.month, value.day): value for value in available_dates}
        movie_titles = self._movie_titles(time_soup)

        results: list[ScrapedShowtime] = []
        for movie_id in self._movie_ids(time_soup):
            try:
                movie = self._scrape_movie(movie_id, fallback_title=movie_titles.get(movie_id))
                results.extend(self._scrape_showtimes(movie, date_by_month_day))
            except Exception:
                continue
        return self._dedupe(results)

    def _scrape_movie(self, movie_id: str, fallback_title: str | None = None) -> ScrapedMovie:
        detail_url = f"{SITE_BASE_URL}/movie/inner?{urlencode({'id': movie_id})}"
        soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
        meta = self._movie_meta(soup)
        title = self._first_text(soup, ".page-title-1") or fallback_title or f"Wonderful Movie {movie_id}"
        poster = soup.select_one(".movie_block .poster_wrap img[src]")
        trailer = soup.select_one(".relative_video iframe[src]")
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=urljoin(SITE_BASE_URL, poster.get("src")) if poster else None,
            release_date=self._parse_date(meta.get("上映日期")),
            duration_minutes=self._parse_duration(meta.get("片長")),
            rating=self._rating(meta.get("級別")),
            description=self._description(soup),
            director=meta.get("導演"),
            cast=meta.get("演員"),
            trailer_url=trailer.get("src") if trailer else None,
            detail_url=detail_url,
            source_movie_id=movie_id,
        )

    def _scrape_showtimes(
        self,
        movie: ScrapedMovie,
        date_by_month_day: dict[tuple[int, int], date],
    ) -> list[ScrapedShowtime]:
        url = f"{SITE_BASE_URL}/lightbox/index?{urlencode({'id': movie.source_movie_id})}"
        soup = BeautifulSoup(self._fetch_text(url), "lxml")
        results: list[ScrapedShowtime] = []
        for group in soup.select("ul.time_list"):
            date_node = group.select_one("li.time")
            show_date = self._date_from_group(date_node, date_by_month_day)
            if not show_date:
                continue
            for item in group.select("li:not(.time)"):
                text = self._clean_text(item.get_text(" ", strip=True))
                time_match = re.search(r"\d{1,2}:\d{2}", text or "")
                if not time_match:
                    continue
                start_time = datetime.strptime(time_match.group(0), "%H:%M").time()
                source_key = (
                    f"wonderful:{movie.source_movie_id}:{show_date.isoformat()}:"
                    f"{start_time.strftime('%H:%M')}"
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
                        source="wonderful",
                        source_showtime_id=source_key,
                        version_label="數位",
                        auditorium_brand=None,
                        projection_type="數位",
                        audio_language=None,
                        subtitle_language=None,
                        source_payload={
                            "movie_id": movie.source_movie_id,
                            "lightbox_url": url,
                            "raw_time": text,
                        },
                    )
                )
        return results

    def _movie_ids(self, soup: BeautifulSoup) -> list[str]:
        ids: list[str] = []
        for option in soup.select("#search-movie option[value]"):
            value = option.get("value")
            if value and value != "0" and value not in ids:
                ids.append(value)
        for anchor in soup.select('a[href*="/lightbox/index?id="]'):
            match = re.search(r"id=(\d+)", anchor.get("href") or "")
            if match and match.group(1) not in ids:
                ids.append(match.group(1))
        return ids

    def _movie_titles(self, soup: BeautifulSoup) -> dict[str, str]:
        titles: dict[str, str] = {}
        for anchor in soup.select('a[href*="/lightbox/index?id="]'):
            match = re.search(r"id=(\d+)", anchor.get("href") or "")
            title = self._first_text(anchor, ".movie_title")
            if match and title:
                titles[match.group(1)] = title
        return titles

    def _available_dates(self, soup: BeautifulSoup) -> list[date]:
        dates: list[date] = []
        for option in soup.select("#search-date option[value]"):
            parsed = self._parse_date(option.get("value"))
            if parsed:
                dates.append(parsed)
        return dates

    def _date_from_group(
        self,
        node,
        date_by_month_day: dict[tuple[int, int], date],
    ) -> date | None:
        text = self._clean_text(node.get_text(" ", strip=True) if node else None)
        match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text or "")
        if not match:
            return None
        month = int(match.group(1))
        day = int(match.group(2))
        if (month, day) in date_by_month_day:
            return date_by_month_day[(month, day)]

        today = date.today()
        year = today.year + 1 if today.month == 12 and month == 1 else today.year
        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _movie_meta(self, soup: BeautifulSoup) -> dict[str, str]:
        meta: dict[str, str] = {}
        for row in soup.select(".list_info li.row"):
            label = self._clean_text(row.select_one(".label_block").get_text(" ", strip=True) if row.select_one(".label_block") else None)
            value = self._clean_text(row.select_one(".content_block").get_text(" ", strip=True) if row.select_one(".content_block") else None)
            if not label or not value:
                continue
            key = re.sub(r"\s|　|:|：", "", label)
            meta[key] = value
        return meta

    def _description(self, soup: BeautifulSoup) -> str | None:
        body = soup.select_one(".movie_description")
        if not body:
            return None
        return self._clean_text(body.get_text(" ", strip=True))

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

    def _first_text(self, soup: BeautifulSoup, selector: str) -> str | None:
        node = soup.select_one(selector)
        return self._clean_text(node.get_text(" ", strip=True)) if node else None

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _parse_duration(self, value: str | None) -> int | None:
        if not value:
            return None
        hour_match = re.search(r"(?P<hours>\d+)\s*時", value)
        minute_match = re.search(r"(?P<minutes>\d+)\s*分", value)
        hours = int(hour_match.group("hours")) if hour_match else 0
        minutes = int(minute_match.group("minutes")) if minute_match else 0
        return hours * 60 + minutes or None

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = self._clean_text(value)
        mapping = {
            "普遍": "普遍級",
            "保護": "保護級",
            "輔導12": "輔12級",
            "輔導15": "輔15級",
            "限制": "限制級",
        }
        for key, rating in mapping.items():
            if key in (text or ""):
                return rating
        return text

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
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
