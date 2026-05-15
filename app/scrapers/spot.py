from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.spot.org.tw"
CHAIN = "SPOT Taipei"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="SPOT光點台北電影館",
    city="台北",
    address="台北市中山區中山北路二段18號",
    source_cinema_id="spot-taipei",
)


class SpotScraper:
    """Scraper for SPOT Taipei Film House.

    SPOT publishes current movies as static HTML pages. The homepage links to
    the active movie pages, and each movie page contains its own schedule table.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for movie_url in self._movie_urls():
            try:
                results.extend(self._scrape_movie(movie_url))
            except Exception:
                continue
        return self._dedupe(results)

    def _movie_urls(self) -> list[str]:
        soup = BeautifulSoup(self._fetch_text(SITE_BASE_URL), "lxml")
        urls: list[str] = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            if not re.search(r"/?movies/\d{6}/m\d+/movies\d{6}_m\d+\.html$", href):
                continue
            absolute = urljoin(SITE_BASE_URL + "/", href)
            if absolute not in urls:
                urls.append(absolute)
        return urls

    def _scrape_movie(self, url: str) -> list[ScrapedShowtime]:
        html = self._fetch_text(url)
        soup = BeautifulSoup(html, "lxml")
        movie = self._movie_from_page(soup, url)
        schedule = self._schedule_from_page(soup, url)
        results: list[ScrapedShowtime] = []
        for show_date, start_time in schedule:
            source_key = (
                f"spot:{movie.source_movie_id}:{show_date.isoformat()}:"
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
                    booking_url=url,
                    source="spot",
                    source_showtime_id=source_key,
                    version_label="數位",
                    auditorium_brand=None,
                    projection_type="數位",
                    audio_language=None,
                    subtitle_language=None,
                    source_payload={"movie_url": url},
                )
            )
        return results

    def _movie_from_page(self, soup: BeautifulSoup, url: str) -> ScrapedMovie:
        title_zh = self._first_text(soup, ".movie_title")
        title_en = self._first_text(soup, ".movie_title_eng")
        director = self._first_text(soup, "p.movie_dir")
        detail_text = soup.get_text(" ", strip=True)
        return ScrapedMovie(
            title=title_zh or title_en or self._source_movie_id(url),
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            still_urls=self._image_urls(soup, url) or None,
            duration_minutes=self._runtime(detail_text),
            rating=self._rating(detail_text),
            description=self._description(soup),
            director=director,
            trailer_url=self._trailer_url(soup),
            detail_url=url,
            source_movie_id=self._source_movie_id(url),
        )

    def _schedule_from_page(self, soup: BeautifulSoup, url: str) -> list[tuple[date, datetime.time]]:
        year, fallback_month = self._year_month_from_url(url)
        schedule_table = self._schedule_table(soup)
        if not schedule_table:
            return []

        current_date: date | None = None
        schedule: list[tuple[date, datetime.time]] = []
        for row in schedule_table.select("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue

            date_match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", cells[0])
            if date_match:
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                current_date = date(year, month, day)
                time_candidates = cells[1:]
            else:
                current_date = current_date or date(year, fallback_month, 1)
                time_candidates = cells

            for value in time_candidates:
                time_match = re.search(r"(\d{1,2}):(\d{2})", value)
                if not time_match or not current_date:
                    continue
                show_time = datetime.strptime(time_match.group(0), "%H:%M").time()
                schedule.append((current_date, show_time))
        return schedule

    def _schedule_table(self, soup: BeautifulSoup):
        schedule_label = soup.find(string=re.compile("本片放映時刻"))
        if not schedule_label:
            return None
        node = schedule_label.parent
        while node:
            table = node.find_next("table")
            if table and re.search(r"\d{1,2}\s*/\s*\d{1,2}", table.get_text(" ", strip=True)):
                return table
            node = node.parent
        return None

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
        for node in soup.select(selector):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and not set(text) <= {"-", "—"}:
                return text
        return None

    def _description(self, soup: BeautifulSoup) -> str | None:
        label = soup.find(string=re.compile("本片放映時刻"))
        if not label:
            return None
        body_texts: list[str] = []
        for paragraph in soup.select("p"):
            if label in paragraph.find_all(string=True):
                break
            text = self._clean_text(paragraph.get_text(" ", strip=True))
            if text and len(text) > 20 and "http" not in text:
                body_texts.append(text)
        return "\n\n".join(dict.fromkeys(body_texts[-4:])) or None

    def _image_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        urls: list[str] = []
        for image in soup.select("#abgneBlock img[src], ul.list img[src]"):
            src = image.get("src")
            if not src:
                continue
            absolute = urljoin(page_url, src)
            if absolute not in urls:
                urls.append(absolute)
        return urls

    def _trailer_url(self, soup: BeautifulSoup) -> str | None:
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            if "youtube.com" in href or "youtu.be" in href:
                return href
        return None

    def _year_month_from_url(self, url: str) -> tuple[int, int]:
        match = re.search(r"/movies/(?P<year>\d{4})(?P<month>\d{2})/", url)
        if not match:
            today = date.today()
            return today.year, today.month
        return int(match.group("year")), int(match.group("month"))

    def _source_movie_id(self, url: str) -> str:
        match = re.search(r"/movies/(\d{6})/(m\d+)/movies\d{6}_(m\d+)\.html$", url)
        if not match:
            return url.rstrip("/").rsplit("/", 1)[-1]
        return f"{match.group(1)}-{match.group(2)}"

    def _runtime(self, text: str) -> int | None:
        match = re.search(r"(\d{2,3})\s*min", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _rating(self, text: str) -> str | None:
        if "限制級" in text or "限18" in text:
            return "限制級"
        if "輔15" in text:
            return "輔15級"
        if "輔12" in text:
            return "輔12級"
        if "保護級" in text:
            return "保護級"
        if "普遍級" in text:
            return "普遍級"
        return None

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return re.sub(r"\s+", " ", value).strip() or None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
