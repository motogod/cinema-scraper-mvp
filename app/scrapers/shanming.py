from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.shanmingcinema.com.tw"
SHOWTIMES_URL = f"{SITE_BASE_URL}/showtimes.php"
MOVIES_URL = f"{SITE_BASE_URL}/movies.php?category=1"
SOURCE = "shanming"
CHAIN = "Shanming Cinema"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="山明影城",
    city="南投",
    address="南投縣埔里鎮中山路二段289號5樓",
    source_cinema_id="shanming-cinema",
)


class ShanmingScraper:
    """Scraper for 南投埔里山明影城."""

    def scrape(self) -> list[ScrapedShowtime]:
        index_soup = BeautifulSoup(self._fetch_text(SHOWTIMES_URL), "lxml")
        detail_map = self._movie_detail_map()
        movie_cache: dict[str, ScrapedMovie] = {}
        results: list[ScrapedShowtime] = []

        for showtime_id, label, showtime_url in self._showtime_links(index_soup):
            showtime_soup = BeautifulSoup(self._fetch_text(showtime_url), "lxml")
            detail_url = detail_map.get(showtime_id)
            movie = self._movie_from_showtime_page(
                showtime_soup,
                showtime_id,
                label,
                detail_url,
            )
            cache_key = movie.source_movie_id or showtime_id
            if cache_key not in movie_cache:
                movie_cache[cache_key] = movie
            movie = movie_cache[cache_key]

            for show_date in self._show_dates(showtime_soup):
                for time_text in self._time_texts(showtime_soup):
                    start_time = self._parse_time(time_text)
                    if not start_time:
                        continue
                    hall_name = self._hall_name(time_text)
                    source_showtime_id = (
                        f"{SOURCE}:{showtime_id}:{show_date.isoformat()}:"
                        f"{start_time.strftime('%H:%M')}:{hall_name or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=hall_name,
                            format=self._format_from_label(label),
                            language=None,
                            booking_url=showtime_url,
                            source=SOURCE,
                            source_showtime_id=source_showtime_id,
                            version_label=self._version_label(label),
                            auditorium_brand=None,
                            projection_type=self._format_from_label(label),
                            audio_language=None,
                            subtitle_language=None,
                            source_payload={
                                "showtime_id": showtime_id,
                                "showtime_url": showtime_url,
                            },
                        )
                    )

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("shanming scraper found no showtimes; keeping existing data")
        return results

    def _showtime_links(self, soup: BeautifulSoup) -> list[tuple[str, str, str]]:
        links: list[tuple[str, str, str]] = []
        for link in soup.select('ul.all-movies a[href*="showtimes.php?id="]'):
            href = link.get("href") or ""
            showtime_id = self._query_id(href)
            label = self._clean_text(link.get_text(" ", strip=True))
            if not showtime_id or not label:
                continue
            links.append((showtime_id, label, urljoin(SITE_BASE_URL, href)))
        return links

    def _movie_detail_map(self) -> dict[str, str]:
        soup = BeautifulSoup(self._fetch_text(MOVIES_URL), "lxml")
        detail_by_showtime: dict[str, str] = {}
        for block in soup.select("div.movies-list"):
            detail = block.select_one('a[href*="movie-info.php?id="]')
            showtime = block.select_one('a[href*="showtimes.php?id="]')
            if not detail or not showtime:
                continue
            showtime_id = self._query_id(showtime.get("href"))
            if showtime_id:
                detail_by_showtime[showtime_id] = urljoin(SITE_BASE_URL, detail.get("href") or "")
        return detail_by_showtime

    def _movie_from_showtime_page(
        self,
        soup: BeautifulSoup,
        showtime_id: str,
        label: str,
        detail_url: str | None,
    ) -> ScrapedMovie:
        title = self._clean_movie_title(
            self._first_text(soup, ".showtimes-header h1") or label
        )
        original_title = self._first_text(soup, ".showtimes-header h2")
        duration = self._duration_minutes(self._first_text(soup, ".showtimes-header .length"))
        rating = self._rating(self._first_text(soup, ".showtimes-header .level"))

        detail_movie = self._movie_from_detail(detail_url, title) if detail_url else None
        return ScrapedMovie(
            title=detail_movie.title if detail_movie and detail_movie.title else title,
            title_zh=detail_movie.title_zh if detail_movie else title,
            title_en=detail_movie.title_en if detail_movie else original_title,
            original_title=detail_movie.original_title if detail_movie else original_title,
            poster_url=detail_movie.poster_url if detail_movie else None,
            release_date=detail_movie.release_date if detail_movie else None,
            duration_minutes=detail_movie.duration_minutes if detail_movie and detail_movie.duration_minutes else duration,
            rating=detail_movie.rating if detail_movie and detail_movie.rating else rating,
            genre=detail_movie.genre if detail_movie else None,
            description=detail_movie.description if detail_movie else None,
            cast=detail_movie.cast if detail_movie else None,
            trailer_url=detail_movie.trailer_url if detail_movie else None,
            detail_url=detail_url or urljoin(SITE_BASE_URL, f"showtimes.php?id={showtime_id}"),
            source_movie_id=self._query_id(detail_url) or showtime_id,
        )

    def _movie_from_detail(self, detail_url: str | None, fallback_title: str) -> ScrapedMovie | None:
        if not detail_url:
            return None
        try:
            soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
        except Exception:
            return None

        article = soup.select_one(".article") or soup
        title = self._clean_text(self._text_after_info(article))
        title_node = article.select_one(".title")
        if title_node:
            title = self._clean_text(title_node.get_text(" ", strip=True))

        original_title = self._first_text(article, "i.subtitle")
        return ScrapedMovie(
            title=title or fallback_title,
            title_zh=title or fallback_title,
            title_en=original_title,
            original_title=original_title,
            poster_url=self._poster_url(article, detail_url),
            release_date=self._parse_date(self._label_value(article, "上映日期")),
            duration_minutes=self._duration_minutes(self._label_value(article, "片長")),
            rating=self._rating(self._label_value(article, "級數")),
            genre=self._clean_genre(self._label_value(article, "類型")),
            description=self._description(article),
            cast=self._label_value(article, "演員"),
            trailer_url=self._trailer_url(article, detail_url),
            detail_url=detail_url,
            source_movie_id=self._query_id(detail_url),
        )

    def _show_dates(self, soup: BeautifulSoup) -> list[date]:
        title = self._first_text(soup, ".showtimes-list .title")
        if not title:
            return []
        match = re.search(
            r"(?P<sm>\d{1,2})月(?P<sd>\d{1,2})日.*?-\s*"
            r"(?P<em>\d{1,2})月(?P<ed>\d{1,2})日",
            title,
        )
        if not match:
            return []
        year = date.today().year
        start = date(year, int(match.group("sm")), int(match.group("sd")))
        end = date(year, int(match.group("em")), int(match.group("ed")))
        if end < start:
            end = date(year + 1, end.month, end.day)

        dates: list[date] = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    def _time_texts(self, soup: BeautifulSoup) -> list[str]:
        output: list[str] = []
        for node in soup.select(".showtimes-list .item"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                output.append(text)
        return output

    def _query_id(self, url: str | None) -> str | None:
        parsed = urlparse(url or "")
        values = parse_qs(parsed.query).get("id")
        return values[0] if values else None

    def _format_from_label(self, label: str | None) -> str | None:
        match = re.search(r"\(([^)]+)\)", label or "")
        return match.group(1).strip() if match else "數位"

    def _version_label(self, label: str | None) -> str | None:
        return self._format_from_label(label)

    def _clean_movie_title(self, title: str | None) -> str | None:
        text = self._clean_text(title)
        if not text:
            return None
        return re.sub(r"^\([^)]*\)\s*", "", text).strip() or text

    def _parse_time(self, value: str | None):
        match = re.search(r"(\d{1,2}):(\d{2})", value or "")
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()

    def _hall_name(self, value: str | None) -> str | None:
        match = re.search(r"\(([^)]+廳)\)", value or "")
        return match.group(1).strip() if match else None

    def _label_value(self, soup: BeautifulSoup, label: str) -> str | None:
        text = soup.get_text("\n", strip=True)
        match = re.search(rf"{re.escape(label)}：\s*\n?\s*([^\n]+)", text)
        return self._clean_text(match.group(1)) if match else None

    def _text_after_info(self, soup: BeautifulSoup) -> str | None:
        image = soup.select_one('img[src*="upload/movies_"]')
        if not image:
            return None
        for node in image.find_all_next(["div", "a"]):
            classes = set(node.get("class") or [])
            if "title" in classes:
                return node.get_text(" ", strip=True)
        return None

    def _description(self, soup: BeautifulSoup) -> str | None:
        title = self._first_text(soup, ".title")
        if not title:
            return None
        text = soup.get_text("\n", strip=True)
        parts = text.split(title, 1)
        if len(parts) < 2:
            return None
        after_title = parts[1]
        original_title = self._first_text(soup, "i.subtitle")
        if original_title and original_title in after_title:
            after_title = after_title.split(original_title, 1)[1]
        description = after_title.split("回上頁", 1)[0]
        return self._clean_text(description)

    def _poster_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        image = soup.select_one('img[src*="upload/movies_"]')
        return urljoin(base_url, image.get("src") or "") if image else None

    def _trailer_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        iframe = soup.select_one("iframe[src]")
        return urljoin(base_url, iframe.get("src") or "") if iframe else None

    def _duration_minutes(self, value: str | None) -> int | None:
        match = re.search(r"(?:(\d+)\s*時)?\s*(\d+)\s*分", value or "")
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        return hours * 60 + minutes

    def _rating(self, value: str | None) -> str | None:
        text = self._clean_text(value)
        if not text:
            return None
        text = re.sub(r"^級數[：:]\s*", "", text)
        if text == "輔導級":
            return "輔導級"
        return text

    def _clean_genre(self, value: str | None) -> str | None:
        text = self._clean_text(value)
        return re.sub(r"\s+", "、", text) if text else None

    def _parse_date(self, value: str | None) -> date | None:
        match = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
        if not match:
            return None
        return datetime.strptime(match.group(0), "%Y-%m-%d").date()

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

    def _first_text(self, node, selector: str) -> str | None:
        found = node.select_one(selector)
        return self._clean_text(found.get_text(" ", strip=True)) if found else None

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
