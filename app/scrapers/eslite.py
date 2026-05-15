from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://meet.eslite.com"
SCHEDULE_URL = f"{SITE_BASE_URL}/tw/tc/gallery/movieschedule/201803020001"
BOOKING_URL = "https://arthouse.eslite.com/visAgreement.aspx"
CHAIN = "Eslite Art House"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="誠品電影院",
    city="台北",
    address="台北市信義區菸廠路88號B1",
    source_cinema_id="eslite-art-house",
)


class EsliteScraper:
    """Scraper for eslite Art House.

    The public schedule page is static HTML. Each movie is rendered as one
    `.film_list .box`, with date columns and showtime lists.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SCHEDULE_URL), "lxml")
        page_year = self._page_year(soup)
        results: list[ScrapedShowtime] = []
        for box in soup.select(".film_list .box"):
            try:
                results.extend(self._parse_movie_box(box, page_year))
            except Exception:
                continue
        return self._dedupe(results)

    def _parse_movie_box(self, box, page_year: int) -> list[ScrapedShowtime]:
        detail_url = self._detail_url(box)
        movie = self._movie_from_box(box, detail_url)
        results: list[ScrapedShowtime] = []

        for date_node in box.select(".time-swiper .swiper-slide"):
            show_date = self._parse_schedule_date(date_node.select_one("p"), page_year)
            if not show_date:
                continue
            for time_node in date_node.select("li"):
                start_time = self._parse_time(time_node.get_text(" ", strip=True))
                if not start_time:
                    continue
                source_key = (
                    f"eslite:{movie.source_movie_id}:{show_date.isoformat()}:"
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
                        booking_url=BOOKING_URL,
                        source="eslite",
                        source_showtime_id=source_key,
                        version_label="數位",
                        auditorium_brand=None,
                        projection_type="數位",
                        audio_language=None,
                        subtitle_language=self._subtitle_language(box),
                        source_payload={
                            "schedule_url": SCHEDULE_URL,
                            "detail_url": detail_url,
                        },
                    )
                )
        return results

    def _movie_from_box(self, box, detail_url: str | None) -> ScrapedMovie:
        title_text = self._movie_title(box)
        title_zh, title_en = self._split_title(title_text)
        return ScrapedMovie(
            title=title_zh or title_text or self._source_movie_id(detail_url, title_text),
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=self._poster_url(box),
            release_date=None,
            duration_minutes=self._duration_minutes(box),
            rating=self._rating(box),
            detail_url=detail_url,
            source_movie_id=self._source_movie_id(detail_url, title_text),
        )

    def _movie_title(self, box) -> str | None:
        node = box.select_one(".intro .left p")
        if not node:
            image = box.select_one(".img img[alt]")
            value = image.get("alt") if image else None
            return self._clean_text(value)
        return self._clean_text(node.get_text(" ", strip=True))

    def _split_title(self, title: str | None) -> tuple[str | None, str | None]:
        if not title:
            return None, None
        title = title.strip()
        double_space = re.search(r"\s{2,}", title)
        if double_space:
            left = title[: double_space.start()]
            right = title[double_space.end() :]
            if re.search(r"[\u4e00-\u9fff]", left) and re.match(r"[A-Za-z]", right):
                return self._clean_text(left), self._clean_text(right)

        for match in re.finditer(r"\s+(?=[A-Za-z])", title):
            left = title[: match.start()]
            right = title[match.end() :]
            if (
                re.search(r"[\u4e00-\u9fff]", left)
                and re.match(r"[A-Za-z]", right)
                and not re.search(r"[\u4e00-\u9fff]", right)
            ):
                return self._clean_text(left), self._clean_text(right)
        return title, None

    def _rating(self, box) -> str | None:
        return self._meta_value(box, "級別")

    def _duration_minutes(self, box) -> int | None:
        value = self._meta_value(box, "片長")
        match = re.search(r"\d+", value or "")
        return int(match.group(0)) if match else None

    def _subtitle_language(self, box) -> str | None:
        value = self._meta_value(box, "字幕")
        if not value:
            return None
        return value.replace("/", "、")

    def _meta_value(self, box, label: str) -> str | None:
        for node in box.select(".intro .right li"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if not text or "：" not in text:
                continue
            key, value = text.split("：", 1)
            if key.strip() == label:
                return value.strip() or None
        return None

    def _poster_url(self, box) -> str | None:
        image = box.select_one(".img img[src]")
        if not image:
            return None
        return urljoin(SITE_BASE_URL, image.get("src") or "")

    def _detail_url(self, box) -> str | None:
        anchor = box.select_one('a.btn-detail-intro[href], a.btn-detail[href]')
        if not anchor:
            return None
        return urljoin(SITE_BASE_URL, anchor.get("href") or "")

    def _source_movie_id(self, detail_url: str | None, title: str | None = None) -> str:
        if detail_url:
            match = re.search(r"/artshow/([^/?#]+)", detail_url)
            if match:
                return match.group(1)
        return re.sub(r"\W+", "", title or "unknown").lower()

    def _parse_schedule_date(self, node, fallback_year: int) -> date | None:
        if not node:
            return None
        match = re.search(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})", node.get_text(" ", strip=True))
        if not match:
            return None
        month = int(match.group("month"))
        day = int(match.group("day"))
        year = fallback_year
        today = date.today()
        if today.month >= 11 and month <= 2:
            year += 1
        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _parse_time(self, value: str | None):
        match = re.search(r"\d{1,2}:\d{2}", value or "")
        if not match:
            return None
        return datetime.strptime(match.group(0), "%H:%M").time()

    def _page_year(self, soup: BeautifulSoup) -> int:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"最後更新時間：(?P<year>\d{4})-", text)
        return int(match.group("year")) if match else date.today().year

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

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
        return text or None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[tuple[str, str]] = set()
        unique: list[ScrapedShowtime] = []
        for item in items:
            key = (item.source, item.source_showtime_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique
