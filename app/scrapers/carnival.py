from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.atmovies.com.tw"
OFFICIAL_BASE_URL = "https://www.3d-movies.tw"
SHOWTIME_URL = f"{SITE_BASE_URL}/showtime/t05502/a05/"
SOURCE = "carnival"
CHAIN = "嘉年華影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="嘉年華影城",
    city="嘉義",
    address="嘉義市中山路617號1F、4F",
    source_cinema_id="t05502",
)


class CarnivalScraper:
    """Scraper for Carnival Cinemas / 嘉年華影城 showtimes.

    The official WebForms showtime page exposes dates, but POSTing a selected
    date currently redirects instead of returning stable showtime markup. The
    theater's @movies page provides the same public showtimes in static HTML.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        first_html = self._fetch_text(SHOWTIME_URL)
        urls = [SHOWTIME_URL, *self._date_urls(first_html)]
        results: list[ScrapedShowtime] = []

        for url in dict.fromkeys(urls):
            soup = BeautifulSoup(
                first_html if url == SHOWTIME_URL else self._fetch_text(url),
                "lxml",
            )
            show_date = self._show_date(soup, url)
            if not show_date:
                continue
            results.extend(self._showtimes_from_page(soup, show_date, url))

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("carnival scraper found no showtimes; keeping existing data")
        return results

    def _showtimes_from_page(
        self,
        soup: BeautifulSoup,
        show_date: date,
        page_url: str,
    ) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for block in soup.select("ul#theaterShowtimeTable"):
            movie = self._movie_from_block(block)
            if not movie:
                continue

            versions = self._version_labels(block)
            version_label = " / ".join(versions) if versions else None
            format_label = self._format_from_versions(versions)
            language = self._language_from_versions(versions)

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
                        booking_url=f"{OFFICIAL_BASE_URL}/time.aspx",
                        source=SOURCE,
                        source_showtime_id=source_showtime_id,
                        version_label=version_label,
                        projection_type=format_label,
                        audio_language=language,
                        source_payload={
                            "movie_id": movie.source_movie_id,
                            "versions": versions,
                            "source_page": page_url,
                            "official_page": f"{OFFICIAL_BASE_URL}/time.aspx",
                        },
                    )
                )
        return results

    def _movie_from_block(self, block) -> ScrapedMovie | None:
        link = block.select_one("li.filmTitle a[href]")
        title = self._clean_text(link.get_text(" ", strip=True) if link else None)
        if not title:
            return None

        detail_url = urljoin(SITE_BASE_URL, link.get("href")) if link else None
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=self._poster_url(block),
            duration_minutes=self._duration_minutes(block),
            rating=self._rating(block),
            detail_url=detail_url,
            source_movie_id=self._source_movie_id(detail_url),
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

    def _date_urls(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        for link in soup.select('a[href^="/showtime/t05502/a05/"]'):
            href = link.get("href") or ""
            if re.search(r"/\d{8}/?$", href):
                urls.append(urljoin(SITE_BASE_URL, href))
        return urls

    def _show_date(self, soup: BeautifulSoup, page_url: str) -> date | None:
        match = re.search(r"/(\d{8})/?$", page_url)
        if match:
            return datetime.strptime(match.group(1), "%Y%m%d").date()

        heading = soup.find("h3")
        text = heading.get_text(" ", strip=True) if heading else ""
        match = re.search(r"(\d{4})/(\d{2})/(\d{2})", text)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _version_labels(self, block) -> list[str]:
        labels: list[str] = []
        for node in block.select("li.filmVersion"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                labels.append(text)
        return labels

    def _time_texts(self, block) -> list[str]:
        output: list[str] = []
        for node in block.select("li"):
            classes = node.get("class") or []
            if any(cls in {"filmTitle", "filmVersion", "theaterElse"} for cls in classes):
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and re.fullmatch(r"\d{1,2}[：:]\d{2}", text):
                output.append(text)
        return output

    def _parse_time(self, value: str):
        match = re.fullmatch(r"(\d{1,2})[：:](\d{2})", value.strip())
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()

    def _poster_url(self, block) -> str | None:
        image = block.select_one("img[src*='/photo']")
        if not image:
            return None
        return urljoin(SITE_BASE_URL, image.get("src"))

    def _duration_minutes(self, block) -> int | None:
        text = block.get_text(" ", strip=True)
        match = re.search(r"片長[：:]\s*(\d+)分", text)
        return int(match.group(1)) if match else None

    def _rating(self, block) -> str | None:
        image = block.select_one("img[src*='cer_']")
        src = image.get("src") if image else ""
        match = re.search(r"cer_([A-Za-z0-9]+)\.", src or "")
        return match.group(1) if match else None

    def _source_movie_id(self, detail_url: str | None) -> str | None:
        if not detail_url:
            return None
        match = re.search(r"/movie/([^/]+)/?", detail_url)
        return match.group(1) if match else None

    def _format_from_versions(self, versions: list[str]) -> str | None:
        joined = " ".join(versions).upper()
        if "3D" in joined:
            return "3D"
        if "2D" in joined:
            return "2D"
        if "ATMOS" in joined:
            return "ATMOS"
        if versions:
            return "數位"
        return None

    def _language_from_versions(self, versions: list[str]) -> str | None:
        joined = " ".join(versions)
        if "日文" in joined or "日語" in joined:
            return "日語"
        if "英文" in joined or "英語" in joined:
            return "英語"
        if "國語" in joined:
            return "國語"
        if "中文" in joined:
            return "中文"
        return None

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
