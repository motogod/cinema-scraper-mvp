from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.ilanmovie.com"
SOURCE = "ilanmovie"
CHAIN = "宜蘭電影資訊網"
CINEMAS = [
    (
        f"{SITE_BASE_URL}/index.php",
        ScrapedCinema(
            chain=CHAIN,
            name="日新戲院",
            city="宜蘭",
            address="宜蘭縣羅東鎮中山西街17-1號",
            source_cinema_id="rishin",
        ),
    ),
    (
        f"{SITE_BASE_URL}/index3.php",
        ScrapedCinema(
            chain=CHAIN,
            name="日新戲院-統一廳",
            city="宜蘭",
            address="宜蘭縣羅東鎮公園路100號3樓",
            source_cinema_id="rishin-tongyi",
        ),
    ),
]


class IlanMovieScraper:
    """Scraper for Ilan Movie / Ri Shin Cinemas showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for url, cinema in CINEMAS:
            soup = BeautifulSoup(self._fetch_text(url), "lxml")
            for block in soup.select(".box1"):
                movie = self._movie_from_block(block, url)
                if not movie:
                    continue
                results.extend(self._showtimes_from_block(block, cinema, movie, url))

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("ilanmovie scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_block(self, block, page_url: str) -> ScrapedMovie | None:
        poster = block.select_one(".box1-body-img img.img-responsive[src]")
        title = self._clean_text(poster.get("alt") if poster else None)
        if not title:
            title_node = block.select_one(".box1-body-content-title")
            title = self._title_from_title_node(title_node)
        if not title:
            return None

        meta_text = self._clean_text(
            block.select_one(".box1-title-2").get_text(" ", strip=True)
            if block.select_one(".box1-title-2")
            else None
        )
        source_movie_id = self._movie_id_from_poster(poster.get("src") if poster else None)
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=urljoin(SITE_BASE_URL, poster.get("src")) if poster else None,
            duration_minutes=self._duration_minutes(meta_text),
            rating=self._rating(block),
            genre=self._genre(meta_text),
            description=self._description(block),
            trailer_url=self._trailer_url(block),
            detail_url=page_url,
            source_movie_id=source_movie_id or title,
        )

    def _showtimes_from_block(
        self,
        block,
        cinema: ScrapedCinema,
        movie: ScrapedMovie,
        page_url: str,
    ) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for row in block.select("table.M-T-T tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            show_date = self._parse_date(cells[0].get_text(" ", strip=True))
            if not show_date:
                continue
            for raw_time in re.findall(r"\d{1,2}:\d{2}", cells[1].get_text(" ", strip=True)):
                start_time = datetime.strptime(raw_time, "%H:%M").time()
                actual_date = show_date + timedelta(days=1) if start_time.hour < 6 else show_date
                source_showtime_id = (
                    f"{SOURCE}:{cinema.source_cinema_id}:{movie.source_movie_id}:"
                    f"{actual_date.isoformat()}T{start_time.strftime('%H:%M')}"
                )
                results.append(
                    ScrapedShowtime(
                        cinema=cinema,
                        movie=movie,
                        show_date=actual_date,
                        start_time=start_time,
                        hall_name=None,
                        format="數位",
                        language=self._language_from_title(movie.title),
                        booking_url=page_url,
                        source=SOURCE,
                        source_showtime_id=source_showtime_id,
                        projection_type="數位",
                        audio_language=self._language_from_title(movie.title),
                        source_payload={
                            "movie_id": movie.source_movie_id,
                            "cinema_id": cinema.source_cinema_id,
                            "source_page": page_url,
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

    def _parse_date(self, value: str) -> date | None:
        match = re.search(r"(\d{1,2})/(\d{1,2})", value)
        if not match:
            return None
        today = date.today()
        parsed = date(today.year, int(match.group(1)), int(match.group(2)))
        if parsed < today - timedelta(days=180):
            parsed = date(today.year + 1, parsed.month, parsed.day)
        return parsed

    def _movie_id_from_poster(self, poster_url: str | None) -> str | None:
        match = re.search(r"/([^/]+)\.(?:jpg|jpeg|png|webp)", poster_url or "", re.IGNORECASE)
        return match.group(1) if match else None

    def _duration_minutes(self, meta_text: str | None) -> int | None:
        match = re.search(r"片長[:：]?\s*(\d+)分", meta_text or "")
        return int(match.group(1)) if match else None

    def _genre(self, meta_text: str | None) -> str | None:
        match = re.search(r"類型[:：]\s*(.+?)(?:/|／|片長|$)", meta_text or "")
        return self._clean_text(match.group(1)) if match else None

    def _rating(self, block) -> str | None:
        image = block.select_one(".box1-body-content-title img[src*='/images/com/s1_']")
        src = image.get("src") if image else ""
        rating_map = {
            "01": "普遍級",
            "02": "保護級",
            "03": "輔導級",
            "04": "限制級",
        }
        match = re.search(r"s1_(\d+)\.", src or "")
        return rating_map.get(match.group(1)) if match else None

    def _description(self, block) -> str | None:
        modal = block.select_one(".modal-body")
        if not modal:
            return None
        for iframe in modal.select("iframe"):
            iframe.decompose()
        text = modal.get_text(" ", strip=True)
        return self._clean_text(text)

    def _trailer_url(self, block) -> str | None:
        iframe = block.select_one("iframe[src]")
        return iframe.get("src") if iframe else None

    def _title_from_title_node(self, title_node) -> str | None:
        if not title_node:
            return None
        texts = [
            self._clean_text(node.get_text(" ", strip=True))
            for node in title_node.find_all("div")
        ]
        values = [text for text in texts if text]
        return values[-1] if values else None

    def _language_from_title(self, title: str | None) -> str | None:
        if title and "中文版" in title:
            return "中文"
        if title and "英文版" in title:
            return "英語"
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
