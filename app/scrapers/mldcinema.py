from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://mldcinema.com.tw"
SHOWTIME_URL = f"{SITE_BASE_URL}/TimeList.php"
SOURCE = "mldcinema"
CHAIN = "MLD台鋁影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="MLD台鋁影城",
    city="高雄",
    address="高雄市前鎮區忠勤路8號",
    source_cinema_id="mldcinema",
)


class MLDCinemaScraper:
    """Scraper for MLD Cinema / 台鋁影城 showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SHOWTIME_URL), "lxml")
        results: list[ScrapedShowtime] = []

        for block in soup.select(".showingBox"):
            movie = self._movie_from_block(block)
            if not movie:
                continue

            format_label = self._format_from_title(movie.title)
            language = self._language_from_title(movie.title)
            version_label = self._version_label(format_label, language)

            for show_date, start_time, booking_url, computer_id in self._showtimes(block):
                source_showtime_id = (
                    f"{SOURCE}:{movie.source_movie_id or movie.title}:"
                    f"{show_date.isoformat()}T{start_time.strftime('%H:%M')}:"
                    f"{computer_id or ''}:{version_label or ''}"
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
                        booking_url=booking_url,
                        source=SOURCE,
                        source_showtime_id=source_showtime_id,
                        version_label=version_label,
                        projection_type=format_label,
                        audio_language=language,
                        source_payload={
                            "computer_id": computer_id,
                            "source_page": SHOWTIME_URL,
                        },
                    )
                )

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("mldcinema scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_block(self, block) -> ScrapedMovie | None:
        title = self._first_text(block, ".photoBox .title")
        if not title:
            return None

        detail_link = block.select_one('a.description[href], .photo a[href*="movieContent.php"]')
        detail_url = urljoin(SITE_BASE_URL, detail_link.get("href")) if detail_link else None
        movie_id = self._movie_id(block, detail_url)
        return ScrapedMovie(
            title=title,
            title_zh=title,
            title_en=self._first_text(block, ".photoBox .text"),
            poster_url=self._poster_url(block),
            duration_minutes=self._duration_minutes(block),
            rating=self._rating(block),
            detail_url=detail_url,
            source_movie_id=movie_id,
        )

    def _showtimes(self, block) -> list[tuple[date, datetime.time, str | None, str | None]]:
        results: list[tuple[date, datetime.time, str | None, str | None]] = []
        for dl in block.select(".dateBox dl"):
            show_date = self._parse_date(dl.select_one("dt"))
            if not show_date:
                continue
            for link in dl.select("dd a[href]"):
                start_time = self._parse_time(link.get_text(" ", strip=True))
                if not start_time:
                    continue
                booking_url = self._booking_url(link)
                results.append((show_date, start_time, booking_url, self._computer_id(link)))
        return results

    def _movie_id(self, block, detail_url: str | None) -> str | None:
        buy_link = block.select_one('a.buy[onclick], a.buy[onClick]')
        onclick = buy_link.get("onclick") or buy_link.get("onClick") if buy_link else ""
        match = re.search(r"movieid=(\d+)", onclick or "")
        if match:
            return match.group(1)
        query = parse_qs(urlparse(detail_url or "").query)
        values = query.get("MN")
        return values[0] if values else None

    def _booking_url(self, link) -> str | None:
        onclick = link.get("onclick") or link.get("onClick") or ""
        match = re.search(r"LinkAlert\('([^']+)'\)", onclick)
        if match:
            return urljoin(SITE_BASE_URL, match.group(1))
        href = link.get("href")
        return urljoin(SITE_BASE_URL, href) if href else None

    def _computer_id(self, link) -> str | None:
        text = " ".join([link.get("href") or "", link.get("onclick") or "", link.get("onClick") or ""])
        match = re.search(r"computerid=(\d+)", text)
        return match.group(1) if match else None

    def _poster_url(self, block) -> str | None:
        image = block.select_one(".photo img[style], .photo img[src]")
        if not image:
            return None
        style = image.get("style") or ""
        match = re.search(r"background\s*:\s*url\(([^)]+)\)", style)
        if match:
            return urljoin(SITE_BASE_URL, match.group(1).strip("'\""))
        return urljoin(SITE_BASE_URL, image.get("src") or "")

    def _duration_minutes(self, block) -> int | None:
        for item in block.select(".dateBoxHd li"):
            text = self._clean_text(item.get_text(" ", strip=True)) or ""
            match = re.search(r"片長[：:]\s*(\d+)\s*分鐘", text)
            if match:
                return int(match.group(1))
        return None

    def _rating(self, block) -> str | None:
        for item in block.select(".dateBoxHd li"):
            text = self._clean_text(item.get_text(" ", strip=True)) or ""
            match = re.search(r"級別[：:]\s*(.+)$", text)
            if match:
                return match.group(1).strip() or None
        return None

    def _format_from_title(self, title: str) -> str:
        if "3D" in title.upper():
            return "3D"
        return "數位"

    def _language_from_title(self, title: str) -> str | None:
        if title.startswith("(中)") or title.startswith("（中）"):
            return "中文"
        if title.startswith("(英)") or title.startswith("（英）"):
            return "英語"
        if title.startswith("(日)") or title.startswith("（日）"):
            return "日語"
        return None

    def _version_label(self, format_label: str | None, language: str | None) -> str | None:
        parts = [part for part in [format_label, language] if part]
        return " / ".join(parts) if parts else None

    def _parse_date(self, node) -> date | None:
        text = node.get_text(" ", strip=True) if node else ""
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _parse_time(self, value: str | None):
        match = re.search(r"(\d{1,2}):(\d{2})", value or "")
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

    def _clean_text(self, value) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None
