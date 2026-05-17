from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.timescinema.com.tw"
TIMES_URL = f"{SITE_BASE_URL}/times.php"
SOURCE = "timescinema"
CHAIN = "清水時代影城"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="清水時代影城",
    city="台中",
    address="台中市清水區光復街65號3樓",
    source_cinema_id="timescinema",
)


class TimesCinemaScraper:
    """Scraper for 清水時代影城 showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        root_soup = BeautifulSoup(self._fetch_text(TIMES_URL), "lxml")
        schedule_urls = self._schedule_urls(root_soup)
        if not schedule_urls:
            schedule_urls = [(TIMES_URL, None)]

        results: list[ScrapedShowtime] = []
        visited: set[str] = set()
        for url, label in schedule_urls:
            for page_url in self._page_urls(url):
                normalized_url = self._normalized_url(page_url)
                if normalized_url in visited:
                    continue
                visited.add(normalized_url)
                soup = BeautifulSoup(self._fetch_text(page_url), "lxml")
                date_range = self._date_range(label or self._active_schedule_label(soup))
                if not date_range:
                    continue
                for block in soup.select(".times_sort"):
                    movie = self._movie_from_block(block)
                    if not movie:
                        continue
                    results.extend(self._showtimes_from_block(block, movie, date_range, page_url))

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("timescinema scraper found no showtimes; keeping existing data")
        return results

    def _schedule_urls(self, soup: BeautifulSoup) -> list[tuple[str, str | None]]:
        links: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        schedule_list = soup.select_one("#schedule_list")
        if not schedule_list:
            return links
        for link in schedule_list.select('a[href*="showtimes="]'):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(SITE_BASE_URL, href)
            if url in seen:
                continue
            seen.add(url)
            links.append((url, self._clean_text(link.get_text(" ", strip=True))))
        return links

    def _page_urls(self, schedule_url: str) -> list[str]:
        soup = BeautifulSoup(self._fetch_text(schedule_url), "lxml")
        urls = [schedule_url]
        seen = {self._normalized_url(schedule_url)}
        for link in soup.select('a[href*="pageNum_times_sort="]'):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(SITE_BASE_URL, href)
            normalized_url = self._normalized_url(url)
            if normalized_url in seen:
                continue
            seen.add(normalized_url)
            urls.append(url)
        return urls

    def _movie_from_block(self, block) -> ScrapedMovie | None:
        title_node = block.select_one(".times_sort_title")
        raw_title = self._clean_text(title_node.get_text(" ", strip=True) if title_node else None)
        if not raw_title:
            return None
        title, version_label, language = self._split_title(raw_title)
        image = block.select_one(".times_sort_left img[src]")
        detail = self._details(block)
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=urljoin(SITE_BASE_URL, image.get("src")) if image else None,
            release_date=self._parse_release_date(detail.get("上映日期")),
            duration_minutes=self._duration_minutes(detail.get("片長")),
            rating=self._rating(detail.get("片長")),
            director=detail.get("導演"),
            cast=detail.get("演員"),
            source_movie_id=self._movie_id(raw_title, image.get("src") if image else None),
        )

    def _showtimes_from_block(
        self,
        block,
        movie: ScrapedMovie,
        show_dates: list[date],
        page_url: str,
    ) -> list[ScrapedShowtime]:
        raw_title = self._node_text(block, ".times_sort_title") or movie.title
        _, version_label, language = self._split_title(raw_title)
        detail = self._details(block)
        default_hall = detail.get("廳別")
        results: list[ScrapedShowtime] = []

        for row in block.select("#times_table tr"):
            row_texts = [self._clean_text(cell.get_text(" ", strip=True)) for cell in row.select("td")]
            row_hall = self._row_hall(row_texts) or default_hall
            for value in row_texts:
                if not value or not re.fullmatch(r"\d{1,2}:\d{2}", value):
                    continue
                try:
                    start_time = datetime.strptime(value, "%H:%M").time()
                except ValueError:
                    continue
                for show_date in show_dates:
                    source_showtime_id = (
                        f"{SOURCE}:{movie.source_movie_id}:"
                        f"{show_date.isoformat()}T{start_time.strftime('%H:%M')}:"
                        f"{row_hall or ''}:{version_label or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=row_hall,
                            format="數位版" if version_label and "數位版" in version_label else None,
                            language=language,
                            booking_url=page_url,
                            source=SOURCE,
                            source_showtime_id=source_showtime_id,
                            version_label=version_label,
                            auditorium_brand=row_hall,
                            projection_type="數位版" if version_label and "數位版" in version_label else None,
                            audio_language=language,
                            source_payload={
                                "raw_title": raw_title,
                                "hall": row_hall,
                                "date_range": [item.isoformat() for item in show_dates],
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

    def _active_schedule_label(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one("#schedule_list .showtimes_list2")
        return self._clean_text(node.get_text(" ", strip=True) if node else None)

    def _date_range(self, label: str | None) -> list[date]:
        if not label:
            return []
        match = re.search(r"(\d{1,2})月(\d{1,2})日\s*~\s*(?:(\d{1,2})月)?(\d{1,2})日", label)
        if not match:
            return []
        today = date.today()
        start_month = int(match.group(1))
        start_day = int(match.group(2))
        end_month = int(match.group(3) or start_month)
        end_day = int(match.group(4))
        start_year = today.year
        end_year = start_year + 1 if end_month < start_month else start_year
        start_date = date(start_year, start_month, start_day)
        end_date = date(end_year, end_month, end_day)
        if end_date < start_date:
            return [start_date]
        days = (end_date - start_date).days + 1
        return [date.fromordinal(start_date.toordinal() + offset) for offset in range(days)]

    def _split_title(self, raw_title: str) -> tuple[str, str | None, str | None]:
        labels = re.findall(r"[（(]([^()（）]+)[)）]", raw_title)
        title = re.sub(r"[（(][^()（）]+[)）]", "", raw_title)
        language = None
        if title.endswith("中文版"):
            language = "國語"
            labels.append("中文版")
            title = title.removesuffix("中文版")
        elif title.endswith("英文版"):
            language = "英語"
            labels.append("英文版")
            title = title.removesuffix("英文版")
        version_label = " ".join(label.strip() for label in labels if label.strip()) or None
        return self._clean_text(title) or raw_title, version_label, language

    def _details(self, block) -> dict[str, str]:
        details: dict[str, str] = {}
        content = block.select_one(".times_sort_content")
        if not content:
            return details
        for paragraph in content.select("p"):
            text = self._clean_text(paragraph.get_text(" ", strip=True))
            if not text or "：" not in text:
                continue
            key, value = text.split("：", 1)
            details[key.strip()] = value.strip()
        return details

    def _duration_minutes(self, value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"(?:(\d+)\s*時)?\s*(\d+)\s*分", value)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        return hours * 60 + minutes

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        for rating in ["普遍級", "保護級", "輔導級", "限制級"]:
            if rating in value:
                return rating
        return None

    def _parse_release_date(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _row_hall(self, values: list[str | None]) -> str | None:
        for value in reversed(values):
            if not value:
                continue
            match = re.search(r"[←<\-]+\s*(.+廳)", value)
            if match:
                return self._clean_text(match.group(1))
        return None

    def _movie_id(self, raw_title: str, image_src: str | None) -> str:
        if image_src:
            image_name = image_src.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            return f"{self._slug(raw_title)}:{image_name}"
        return self._slug(raw_title)

    def _normalized_url(self, url: str) -> str:
        parsed = urlparse(urljoin(SITE_BASE_URL, url))
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))

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

    def _slug(self, value: str) -> str:
        return re.sub(r"\s+", "-", value.strip().lower())

    def _clean_text(self, value) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
        return text or None
