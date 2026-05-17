from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.ccmovie.com.tw"
SHOWTIMES_URL = f"{SITE_BASE_URL}/product.php?_path=product_showtimes"
SOURCE = "ccmovie"
CHAIN = "親親影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="親親影城",
    city="台中",
    address="台中市北區北屯路14號(台中監理站對面)",
    source_cinema_id="ccmovie",
)

HALL_NAMES = {
    "1": "一廳",
    "2": "二廳",
    "3": "三廳",
    "5": "五廳",
    "6": "六廳",
    "7": "七廳",
    "8": "八廳",
}


class CcMovieScraper:
    """Scraper for Chin Chin Cinema / 親親影城 showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SHOWTIMES_URL), "lxml")
        results: list[ScrapedShowtime] = []
        for block in soup.select(".showtime-item[id^='m_']"):
            movie = self._movie_from_block(block)
            if not movie:
                continue
            results.extend(self._showtimes_from_block(block, movie))

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("ccmovie scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_block(self, block) -> ScrapedMovie | None:
        title_node = block.select_one(".theater-box .m_title")
        title = self._clean_text(title_node.contents[0] if title_node and title_node.contents else None)
        if not title:
            return None

        movie_id = (block.get("id") or "").removeprefix("m_")
        detail_link = block.select_one('a.pro_price[href*="product_detail"][href*="id="]')
        return ScrapedMovie(
            title=title,
            title_zh=title,
            title_en=self._node_text(block, ".m_title .eng"),
            poster_url=self._poster_url(block),
            duration_minutes=self._duration_minutes(block),
            rating=self._rating(block),
            detail_url=urljoin(SITE_BASE_URL, detail_link.get("href")) if detail_link else None,
            trailer_url=self._trailer_url(block),
            source_movie_id=movie_id or title,
        )

    def _showtimes_from_block(self, block, movie: ScrapedMovie) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for pane in block.select(".tab-pane"):
            date_node = pane.select_one(".dateDisplay")
            show_date = self._parse_date(date_node.get_text(" ", strip=True) if date_node else None)
            if not show_date:
                continue

            for version_node in pane.select(".dateMovie"):
                showtimes_node = self._next_showtimes_node(version_node)
                if not showtimes_node:
                    continue
                version_label = self._version_label(version_node, movie.title)
                format_label = self._format_from_version(version_label)
                version_language = self._language_from_version(version_label)

                for time_node in showtimes_node.select("li.sky_word"):
                    raw_time = self._node_text(time_node, ".info")
                    if not raw_time:
                        continue
                    try:
                        start_time = datetime.strptime(raw_time, "%H:%M").time()
                    except ValueError:
                        continue

                    actual_date = show_date + timedelta(days=1) if start_time.hour < 6 else show_date
                    hall_name = self._hall_name(time_node)
                    source_showtime_id = (
                        f"{SOURCE}:{movie.source_movie_id}:"
                        f"{actual_date.isoformat()}T{start_time.strftime('%H:%M')}:"
                        f"{hall_name or ''}:{version_label or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=actual_date,
                            start_time=start_time,
                            hall_name=hall_name,
                            format=format_label,
                            language=version_language,
                            booking_url=SHOWTIMES_URL,
                            source=SOURCE,
                            source_showtime_id=source_showtime_id,
                            version_label=version_label,
                            auditorium_brand=hall_name,
                            projection_type=format_label,
                            audio_language=version_language,
                            source_payload={
                                "movie_id": movie.source_movie_id,
                                "hall": hall_name,
                                "version": version_label,
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

    def _next_showtimes_node(self, version_node):
        node = version_node.find_next_sibling()
        while node is not None:
            classes = node.get("class") or []
            if "movie_showtimes" in classes:
                return node
            if "dateMovie" in classes:
                return None
            node = node.find_next_sibling()
        return None

    def _version_label(self, version_node, movie_title: str) -> str | None:
        text = self._clean_text(version_node.get_text(" ", strip=True))
        if not text:
            return None
        text = re.sub(r"^\s*[\uf0ca\s]+", "", text)
        text = text.replace("『", "").replace("』", "").strip()
        return None if text == movie_title else text

    def _poster_url(self, block) -> str | None:
        image = block.select_one("img.pro_spic[src]")
        return urljoin(SITE_BASE_URL, image.get("src")) if image else None

    def _duration_minutes(self, block) -> int | None:
        text = self._clean_text(block.get_text(" ", strip=True)) or ""
        match = re.search(r"片長[:：]\s*(\d+)\s*分鐘", text)
        return int(match.group(1)) if match else None

    def _rating(self, block) -> str | None:
        image = block.select_one("span.movie_pants img[src*='/regrading/']")
        src = image.get("src") if image else ""
        match = re.search(r"/regrading/(\d+)\.", src or "")
        if not match:
            return None
        return {
            "0": "普遍級",
            "6": "保護級",
            "12": "輔導十二歲級",
            "15": "輔導十五歲級",
            "18": "限制級",
        }.get(match.group(1))

    def _trailer_url(self, block) -> str | None:
        link = block.select_one('a.lightview[href*="youtube.com/embed"]')
        return link.get("href") if link else None

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _format_from_version(self, version_label: str | None) -> str | None:
        if not version_label:
            return None
        if "3D" in version_label.upper():
            return "3D"
        if "2D" in version_label.upper():
            return "2D"
        return None

    def _language_from_version(self, version_label: str | None) -> str | None:
        if not version_label:
            return None
        if "日語" in version_label or "日文" in version_label:
            return "日語"
        if "英語" in version_label or "英文" in version_label:
            return "英語"
        if "國語" in version_label:
            return "國語"
        if "中文" in version_label:
            return "中文"
        return None

    def _hall_name(self, time_node) -> str | None:
        image = time_node.select_one("img[src]")
        src = image.get("src") if image else ""
        match = re.search(r"generally(\d+)\.png", src)
        if match:
            return HALL_NAMES.get(match.group(1))
        return None

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
