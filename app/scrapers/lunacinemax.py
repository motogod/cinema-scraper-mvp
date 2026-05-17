from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.lunacinemax.com.tw"
SHOWTIME_URL = f"{SITE_BASE_URL}/showtime.aspx"
SOURCE = "lunacinemax"
CHAIN = "新月豪華影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="新月豪華影城",
    city="宜蘭",
    address="宜蘭縣宜蘭市民權路二段38巷2號(新月廣場內)",
    source_cinema_id="lunacinemax",
)


class LunaCinemaxScraper:
    """Scraper for Luna Digital Cinemax showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SHOWTIME_URL), "lxml")
        results: list[ScrapedShowtime] = []

        for title_node in soup.select('span[id^="DataList1_ctl"][id$="_NAME_CHTLabel0"]'):
            prefix = title_node.get("id", "").removesuffix("_NAME_CHTLabel0")
            movie = self._movie_from_prefix(soup, prefix, title_node)
            if not movie:
                continue
            booking_url = self._booking_url(soup, movie.source_movie_id)
            page_date = self._page_date(soup, prefix)
            for time_node in soup.select(f'span[id^="{prefix}_DataList2_"][id$="_TIMELabel"]'):
                showtime = self._showtime_from_time_node(
                    soup=soup,
                    prefix=prefix,
                    movie=movie,
                    booking_url=booking_url,
                    page_date=page_date,
                    time_node=time_node,
                )
                if showtime:
                    results.append(showtime)

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("lunacinemax scraper found no showtimes; keeping existing data")
        return results

    def _movie_from_prefix(self, soup: BeautifulSoup, prefix: str, title_node) -> ScrapedMovie | None:
        title = self._clean_text(title_node.get_text(" ", strip=True))
        movie_id = self._movie_id_from_prefix(soup, prefix)
        if not title or not movie_id:
            return None

        detail_url = urljoin(SITE_BASE_URL, f"movie_detail.aspx?ID={movie_id}")
        return ScrapedMovie(
            title=title,
            title_zh=title,
            title_en=self._node_text(soup, f"{prefix}_NAME_ENGLabel"),
            poster_url=self._poster_url(soup, movie_id),
            duration_minutes=self._duration_minutes(soup, prefix),
            rating=self._node_text(soup, f"{prefix}_RATINGLabel"),
            detail_url=detail_url,
            source_movie_id=movie_id,
        )

    def _showtime_from_time_node(
        self,
        soup: BeautifulSoup,
        prefix: str,
        movie: ScrapedMovie,
        booking_url: str | None,
        page_date: date,
        time_node,
    ) -> ScrapedShowtime | None:
        raw_time = self._clean_text(time_node.get_text(" ", strip=True))
        if not raw_time:
            return None
        try:
            start_time = datetime.strptime(raw_time, "%H:%M").time()
        except ValueError:
            return None

        show_date = page_date + timedelta(days=1) if start_time.hour < 6 else page_date
        hall_name = self._hall_name(soup, time_node.get("id") or "")
        source_showtime_id = (
            f"{SOURCE}:{movie.source_movie_id}:{show_date.isoformat()}T"
            f"{start_time.strftime('%H:%M')}:{hall_name or ''}"
        )
        language = self._language_from_title(movie.title, movie.title_en)
        return ScrapedShowtime(
            cinema=CINEMA,
            movie=movie,
            show_date=show_date,
            start_time=start_time,
            hall_name=hall_name,
            format="數位",
            language=language,
            booking_url=booking_url,
            source=SOURCE,
            source_showtime_id=source_showtime_id,
            version_label=language,
            audio_language=language,
            source_payload={
                "movie_id": movie.source_movie_id,
                "page_prefix": prefix,
                "time_label_id": time_node.get("id"),
            },
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

    def _page_date(self, soup: BeautifulSoup, prefix: str) -> date:
        label = self._node_text(soup, f"{prefix}_Label3")
        today = date.today()
        if label:
            match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", label)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
                year = today.year
                parsed = date(year, month, day)
                if parsed < today - timedelta(days=180):
                    parsed = date(year + 1, month, day)
                return parsed
        return today

    def _movie_id_from_prefix(self, soup: BeautifulSoup, prefix: str) -> str | None:
        link = soup.select_one(f'a[href^="movie_detail.aspx?ID="] span[id="{prefix}_NAME_CHTLabel0"]')
        if link:
            parent = link.find_parent("a", href=True)
            movie_id = self._movie_id_from_url(parent.get("href")) if parent else None
            if movie_id:
                return movie_id

        title_node = soup.find(id=f"{prefix}_NAME_CHTLabel0")
        block = title_node.find_parent("table") if title_node else None
        for href in [a.get("href") for a in block.select("a[href]")] if block else []:
            movie_id = self._movie_id_from_url(href)
            if movie_id:
                return movie_id
        return None

    def _movie_id_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        query = parse_qs(urlparse(url).query)
        return (query.get("ID") or query.get("pid_for_movie") or [None])[0]

    def _poster_url(self, soup: BeautifulSoup, movie_id: str) -> str | None:
        image = soup.select_one(f'img[src*="/images/poster/{movie_id}."]')
        return urljoin(SITE_BASE_URL, image.get("src")) if image else None

    def _duration_minutes(self, soup: BeautifulSoup, prefix: str) -> int | None:
        text = self._node_text(soup, f"{prefix}_LENGTH")
        match = re.search(r"(\d+)", text or "")
        return int(match.group(1)) if match else None

    def _booking_url(self, soup: BeautifulSoup, movie_id: str | None) -> str | None:
        if not movie_id:
            return None
        link = soup.select_one(f'a[href*="pid_for_movie={movie_id}"]')
        return urljoin(SITE_BASE_URL, link.get("href")) if link else None

    def _hall_name(self, soup: BeautifulSoup, time_label_id: str) -> str | None:
        hall_id = time_label_id.removesuffix("_TIMELabel") + "_SCREEN_NAMELabel"
        return self._node_text(soup, hall_id)

    def _language_from_title(self, title: str | None, title_en: str | None) -> str | None:
        joined = " ".join(value for value in [title, title_en] if value)
        if "中文版" in joined or "(Chinese)" in joined:
            return "中文"
        if "英文版" in joined or "(English)" in joined:
            return "英語"
        return None

    def _node_text(self, soup: BeautifulSoup, node_id: str) -> str | None:
        node = soup.find(id=node_id)
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
