from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.nt-movie.com.tw"
SHOWTIME_URL = f"{SITE_BASE_URL}/showtime.php"
BOOKING_URL = "https://booking.nt-movie.com.tw/"
SOURCE = "nantai"
CHAIN = "南台影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="南台影城",
    city="台南",
    address="台南市中西區友愛街317號",
    source_cinema_id="nt-movie",
)


class NantaiScraper:
    """Scraper for 南台影城 showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        first_html = self._fetch_text(SHOWTIME_URL)
        urls = [SHOWTIME_URL, *self._date_urls(first_html)]
        movie_cache: dict[str, ScrapedMovie] = {}
        results: list[ScrapedShowtime] = []

        for url in dict.fromkeys(urls):
            soup = BeautifulSoup(
                first_html if url == SHOWTIME_URL else self._fetch_text(url),
                "lxml",
            )
            show_date = self._selected_date(soup)
            if not show_date:
                continue
            for block in soup.select("ul#movieList > li"):
                movie = self._movie_from_block(block, movie_cache)
                if not movie:
                    continue
                language = self._language_from_title(movie.title)
                format_label = self._format_from_title(movie.title)
                version_label = self._version_label(format_label, language)

                for time_text in self._time_texts(block):
                    start_time = self._parse_time(time_text)
                    if not start_time:
                        continue
                    source_showtime_id = (
                        f"{SOURCE}:{movie.source_movie_id or movie.title}:"
                        f"{show_date.isoformat()}T{start_time.strftime('%H:%M')}:"
                        f"{version_label or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=None,
                            format=format_label,
                            language=language,
                            booking_url=BOOKING_URL,
                            source=SOURCE,
                            source_showtime_id=source_showtime_id,
                            version_label=version_label,
                            projection_type=format_label,
                            audio_language=language,
                            source_payload={
                                "movie_id": movie.source_movie_id,
                                "source_page": url,
                            },
                        )
                    )

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("nantai scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_block(
        self,
        block,
        movie_cache: dict[str, ScrapedMovie],
    ) -> ScrapedMovie | None:
        detail_link = block.select_one('a[href*="movie_detail.php"][href*="item="]')
        detail_url = urljoin(SITE_BASE_URL, detail_link.get("href")) if detail_link else None
        movie_id = self._movie_id(detail_url)
        cache_key = movie_id or detail_url or ""
        if cache_key and cache_key in movie_cache:
            return movie_cache[cache_key]

        title_zh, title_en = self._titles(block)
        title = title_zh or title_en
        if not title:
            return None

        detail_movie = self._movie_from_detail(detail_url, title_zh, title_en, movie_id)
        if detail_movie:
            movie = detail_movie
        else:
            movie = ScrapedMovie(
                title=title,
                title_zh=title_zh,
                title_en=title_en,
                poster_url=self._poster_url(block, SHOWTIME_URL),
                release_date=self._release_date_from_block(block),
                duration_minutes=self._duration_minutes(block),
                rating=self._rating(block),
                detail_url=detail_url,
                source_movie_id=movie_id,
            )

        if cache_key:
            movie_cache[cache_key] = movie
        return movie

    def _movie_from_detail(
        self,
        detail_url: str | None,
        fallback_title_zh: str | None,
        fallback_title_en: str | None,
        movie_id: str | None,
    ) -> ScrapedMovie | None:
        if not detail_url:
            return None
        try:
            soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
        except Exception:
            return None

        title_zh = self._first_text(soup, ".movie_titleC") or fallback_title_zh
        title_en = self._first_text(soup, ".movie_titleE") or fallback_title_en
        title = title_zh or title_en
        if not title:
            return None

        return ScrapedMovie(
            title=title,
            title_zh=title_zh,
            title_en=title_en,
            poster_url=self._poster_url(soup, detail_url),
            release_date=self._label_date(soup, "上映日期"),
            duration_minutes=self._duration_minutes_from_text(self._label_value(soup, "片長")),
            rating=self._rating(soup),
            genre=self._label_value(soup, "類型"),
            description=self._first_text(soup, "#desc1"),
            director=self._label_value(soup, "導演"),
            cast=self._label_value(soup, "演員"),
            trailer_url=self._trailer_url(soup),
            detail_url=detail_url,
            source_movie_id=movie_id,
        )

    def _date_urls(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        for option in soup.select('select[name="select_day"] option[value]'):
            value = (option.get("value") or "").strip()
            if value and value.isdigit():
                urls.append(f"{SHOWTIME_URL}?day={value}")
        return urls

    def _selected_date(self, soup: BeautifulSoup) -> date | None:
        option = soup.select_one('select[name="select_day"] option[selected]')
        if not option:
            option = soup.select_one('select[name="select_day"] option[value]:not([value=""])')
        return self._parse_date(option.get_text(" ", strip=True) if option else None)

    def _titles(self, block) -> tuple[str | None, str | None]:
        title_node = block.select_one(".movieTitle")
        if not title_node:
            return None, None
        parts = [
            self._clean_text(part)
            for part in title_node.get_text("\n", strip=True).split("\n")
        ]
        parts = [part for part in parts if part]
        title_zh = parts[0] if parts else None
        title_en = parts[1] if len(parts) > 1 else None
        return title_zh, title_en

    def _time_texts(self, block) -> list[str]:
        texts: list[str] = []
        for node in block.select("ul.times li"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and re.fullmatch(r"\d{1,2}:\d{2}", text):
                texts.append(text)
        return texts

    def _movie_id(self, detail_url: str | None) -> str | None:
        query = parse_qs(urlparse(detail_url or "").query)
        values = query.get("item")
        return values[0] if values else None

    def _poster_url(self, block, base_url: str) -> str | None:
        image = block.select_one("img[src*='picture/'][src]")
        return urljoin(base_url, image.get("src") or "") if image else None

    def _rating(self, block) -> str | None:
        image = block.select_one("img.classIcon[src]")
        src = image.get("src") if image else ""
        match = re.search(r"classIcon_(\d+)\.", src or "")
        return f"classIcon_{match.group(1)}" if match else None

    def _release_date_from_block(self, block) -> date | None:
        text = block.get_text(" ", strip=True)
        match = re.search(r"上映日期[：:]\s*(\d{4}-\d{2}-\d{2})", text)
        return self._parse_date(match.group(1) if match else None)

    def _duration_minutes(self, block) -> int | None:
        text = block.get_text(" ", strip=True)
        match = re.search(r"片長[：:]\s*([^上映]+)", text)
        return self._duration_minutes_from_text(match.group(1) if match else None)

    def _duration_minutes_from_text(self, value: str | None) -> int | None:
        text = self._clean_text(value) or ""
        match = re.search(r"(?:(\d+)\s*(?:時|小時))?\s*(\d+)\s*分", text)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        return hours * 60 + minutes

    def _label_value(self, soup: BeautifulSoup, label: str) -> str | None:
        label_key = self._label_key(label)
        for row in soup.select("#movie_Info table tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            key = self._label_key(cells[0].get_text(" ", strip=True))
            if key.startswith(label_key):
                return self._clean_text(cells[1].get_text(" ", strip=True))
        return None

    def _label_key(self, value: str | None) -> str:
        return re.sub(r"[\s　：:]+", "", value or "")

    def _label_date(self, soup: BeautifulSoup, label: str) -> date | None:
        return self._parse_date(self._label_value(soup, label))

    def _trailer_url(self, soup: BeautifulSoup) -> str | None:
        tab = soup.select_one("ul.tab li[data-video]")
        return tab.get("data-video") if tab else None

    def _format_from_title(self, title: str) -> str:
        if "3D" in title.upper():
            return "3D"
        return "數位"

    def _language_from_title(self, title: str) -> str | None:
        if "日文" in title or "《JA》" in title.upper():
            return "日語"
        if "中文" in title or "《ZH》" in title.upper():
            return "中文"
        if "英文" in title or "《EN》" in title.upper():
            return "英語"
        return None

    def _version_label(self, format_label: str | None, language: str | None) -> str | None:
        parts = [part for part in [format_label, language] if part]
        return " / ".join(parts) if parts else None

    def _parse_date(self, value: str | None) -> date | None:
        match = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
        if not match:
            return None
        return datetime.strptime(match.group(0), "%Y-%m-%d").date()

    def _parse_time(self, value: str | None):
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()

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

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None
