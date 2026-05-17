from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.acecinema.com.tw"
MOVIE_ALL_URL = f"{SITE_BASE_URL}/movie/all"
SOURCE = "acecinema"
CHAIN = "王牌映画影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="王牌映画影城-廣三SOGO店",
    city="台中",
    address="台中市西區臺灣大道二段459號18樓",
    source_cinema_id="acecinema-sogo",
)


class AceCinemaScraper:
    """Scraper for ACE ENT Cinemas showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(MOVIE_ALL_URL), "lxml")
        results: list[ScrapedShowtime] = []
        for block in soup.select(".movie_list"):
            movie, version_label, language, format_label = self._movie_from_block(block)
            if not movie:
                continue
            results.extend(
                self._showtimes_from_block(
                    block=block,
                    movie=movie,
                    version_label=version_label,
                    language=language,
                    format_label=format_label,
                )
            )

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("acecinema scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_block(
        self,
        block,
    ) -> tuple[ScrapedMovie | None, str | None, str | None, str | None]:
        detail_link = block.select_one('a[href^="/movie/dtl/"]')
        movie_id = self._movie_id(detail_link.get("href") if detail_link else None)
        raw_title = self._node_text(block, "h3")
        title, version_label, format_label, language = self._parse_title(raw_title)
        if not title or not movie_id:
            return None, None, None, None

        return (
            ScrapedMovie(
                title=title,
                title_zh=title,
                title_en=self._node_text(block, "h4"),
                poster_url=self._poster_url(block),
                duration_minutes=self._duration_minutes(block),
                rating=self._rating(block),
                genre=self._genre(block),
                detail_url=urljoin(SITE_BASE_URL, detail_link.get("href")) if detail_link else None,
                source_movie_id=movie_id,
            ),
            version_label,
            language,
            format_label,
        )

    def _showtimes_from_block(
        self,
        block,
        movie: ScrapedMovie,
        version_label: str | None,
        language: str | None,
        format_label: str | None,
    ) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        booking_url = urljoin(SITE_BASE_URL, f"/booking/res?id={movie.source_movie_id}")
        for row in block.select(".movie_table tr"):
            date_node = row.select_one("th.hidden-xs")
            date_text = self._clean_text(date_node.get_text(" ", strip=True) if date_node else None)
            show_date = self._parse_date(date_text)
            if not show_date:
                continue
            cells = row.find_all("td")
            if not cells:
                continue
            for raw_time in re.findall(r"\d{1,2}:\d{2}", cells[-1].get_text(" ", strip=True)):
                start_time = datetime.strptime(raw_time, "%H:%M").time()
                source_showtime_id = (
                    f"{SOURCE}:{movie.source_movie_id}:"
                    f"{show_date.isoformat()}T{start_time.strftime('%H:%M')}"
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
                            "movie_id": movie.source_movie_id,
                            "source_page": MOVIE_ALL_URL,
                        },
                    )
                )
        return results

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

    def _parse_title(self, raw_title: str | None) -> tuple[str | None, str | None, str | None, str | None]:
        title = self._clean_text(raw_title)
        if not title:
            return None, None, None, None

        version_label = None
        format_label = None
        language = None
        match = re.match(r"^\(([^)]+)\)\s*(.+)$", title)
        if match:
            version_label = match.group(1).strip()
            title = match.group(2).strip()
            if "數位" in version_label:
                format_label = "數位"
            if "日" in version_label:
                language = "日語"
            elif "英" in version_label:
                language = "英語"
            elif "中" in version_label:
                language = "中文"
        return title, version_label, format_label, language

    def _parse_date(self, value: str | None):
        if not value:
            return None
        match = re.search(r"(\d{4})/(\d{2})/(\d{2})", value)
        if not match:
            return None
        return datetime.strptime(match.group(0), "%Y/%m/%d").date()

    def _movie_id(self, href: str | None) -> str | None:
        match = re.search(r"/movie/dtl/(\d+)", href or "")
        return match.group(1) if match else None

    def _poster_url(self, block) -> str | None:
        image = block.select_one(".pic img[src]")
        return urljoin(SITE_BASE_URL, image.get("src")) if image else None

    def _duration_minutes(self, block) -> int | None:
        text = self._node_text(block, "p.txt_gray") or ""
        match = re.search(r"(?:(\d+)\s*時)?\s*(\d+)\s*分", text)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        return hours * 60 + minutes

    def _rating(self, block) -> str | None:
        text = self._node_text(block, "p.txt_gray") or ""
        parts = [part.strip() for part in text.split("｜")]
        return parts[1] if len(parts) > 1 and parts[1] else None

    def _genre(self, block) -> str | None:
        values: list[str] = []
        ignored = {"熱售中", "預售中", "特別場"}
        for node in block.select("span.movie_tag"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and text not in ignored:
                values.append(text)
        return "、".join(values) if values else None

    def _node_text(self, block, selector: str) -> str | None:
        node = block.select_one(selector)
        return self._clean_text(node.get_text(" ", strip=True) if node else None)

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
