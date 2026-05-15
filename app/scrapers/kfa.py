from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://kfa.kcg.gov.tw"
CALENDAR_URL = f"{SITE_BASE_URL}/tw/calendar"
CHAIN = "Kaohsiung Film Archive"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="高雄市電影館",
    city="高雄",
    address="高雄市鹽埕區河西路10號",
    source_cinema_id="kfa",
)


class KfaScraper:
    """Scraper for Kaohsiung Film Archive.

    KFA publishes a monthly calendar as server-rendered HTML. Each calendar
    entry links to a detail page containing poster, specs, and ticket URL.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        movie_cache: dict[str, tuple[ScrapedMovie, str | None, dict[str, str | None]]] = {}
        results: list[ScrapedShowtime] = []

        for calendar_url in self._calendar_urls():
            for entry in self._calendar_entries(calendar_url):
                if entry["show_date"] < date.today():
                    continue

                detail_url = entry["detail_url"]
                if detail_url not in movie_cache:
                    movie_cache[detail_url] = self._movie_from_detail(
                        detail_url,
                        entry["title"],
                        entry["rating"],
                    )

                movie, booking_url, meta = movie_cache[detail_url]
                booking_url = booking_url or detail_url
                source_key = (
                    f"kfa:{movie.source_movie_id}:{entry['show_date'].isoformat()}:"
                    f"{entry['start_time'].strftime('%H:%M')}:{entry['location'] or ''}"
                )
                results.append(
                    ScrapedShowtime(
                        cinema=CINEMA,
                        movie=movie,
                        show_date=entry["show_date"],
                        start_time=entry["start_time"],
                        hall_name=entry["location"],
                        format=meta.get("format") or "DCP",
                        language=meta.get("audio_language"),
                        booking_url=booking_url,
                        source="kfa",
                        source_showtime_id=source_key,
                        version_label=meta.get("format") or "DCP",
                        auditorium_brand=None,
                        projection_type=meta.get("format") or "DCP",
                        audio_language=meta.get("audio_language"),
                        subtitle_language=meta.get("subtitle_language"),
                        source_payload={
                            "calendar_url": calendar_url,
                            "detail_url": detail_url,
                            "location": entry["location"],
                        },
                    )
                )
        return self._dedupe(results)

    def _calendar_urls(self) -> list[str]:
        today = date.today()
        next_month_year = today.year + (1 if today.month == 12 else 0)
        next_month = 1 if today.month == 12 else today.month + 1
        return [
            CALENDAR_URL,
            f"{CALENDAR_URL}/{next_month_year}{next_month:02d}",
        ]

    def _calendar_entries(self, url: str) -> list[dict]:
        soup = BeautifulSoup(self._fetch_text(url), "lxml")
        year, month = self._calendar_year_month(soup)
        entries: list[dict] = []

        for day_node in soup.select("th.calendar__body__day"):
            if "other-month" in (day_node.get("class") or []):
                continue

            day = self._calendar_day(day_node)
            if not day:
                continue
            try:
                show_date = date(year, month, day)
            except ValueError:
                continue

            for programme in day_node.select(".programme"):
                time_text = self._first_text(programme, ".programme__info__text .en")
                detail_anchor = programme.select_one("a[href]")
                detail_url = urljoin(url, detail_anchor["href"]) if detail_anchor else None
                start_time = self._parse_time(time_text)
                if not detail_url or not start_time:
                    continue

                title = self._first_text(programme, ".programme__info__title")
                location = self._first_text(programme, ".programme__info__location")
                entries.append(
                    {
                        "show_date": show_date,
                        "start_time": start_time,
                        "title": title or detail_anchor.get("title") or detail_url,
                        "detail_url": detail_url,
                        "location": location,
                        "rating": self._rating_from_classes(programme),
                    }
                )
        return entries

    def _movie_from_detail(
        self,
        detail_url: str,
        fallback_title: str,
        fallback_rating: str | None,
    ) -> tuple[ScrapedMovie, str | None, dict[str, str | None]]:
        soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
        title = self._first_text(soup, ".page-info__midtitle") or fallback_title
        title_zh, title_en = self._split_title(title)
        meta = self._movie_meta(soup)
        poster_url = self._first_image_url(soup, ".page-info__img-wrap img", detail_url)
        still_urls = self._image_urls(soup, ".preview-slider img", detail_url)
        booking_url = self._booking_url(soup, detail_url)
        format_label = meta.get("放映規格")
        movie = ScrapedMovie(
            title=title,
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=poster_url,
            still_urls=still_urls or None,
            release_date=self._period_start(soup),
            duration_minutes=self._runtime(meta.get("片長")),
            rating=self._rating(meta.get("級別")) or fallback_rating,
            genre=self._first_text(soup, ".page-info__title"),
            description=self._description(soup),
            director=meta.get("導演"),
            trailer_url=self._trailer_url(soup, detail_url),
            detail_url=detail_url,
            source_movie_id=self._source_movie_id(detail_url),
        )
        source_meta = {
            "format": format_label,
            "audio_language": meta.get("發音"),
            "subtitle_language": meta.get("字幕"),
            "country": meta.get("國別"),
        }
        return movie, booking_url, source_meta

    def _movie_meta(self, soup: BeautifulSoup) -> dict[str, str]:
        values: dict[str, str] = {}
        for item in soup.select(".film-spec__list__item"):
            key = self._first_text(item, ".film-spec__list__item__attribute-name")
            value = self._first_text(item, ".film-spec__list__item__value")
            if key and value:
                values[key] = value
        return values

    def _calendar_year_month(self, soup: BeautifulSoup) -> tuple[int, int]:
        label = self._first_text(soup, ".page-info .en.en__title") or ""
        match = re.search(r"(\d{4})\.(\d{1,2})", label)
        if not match:
            today = date.today()
            return today.year, today.month
        return int(match.group(1)), int(match.group(2))

    def _calendar_day(self, day_node) -> int | None:
        number_node = day_node.select_one(".calendar__body__day__number")
        text = number_node.get_text(" ", strip=True) if number_node else ""
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None

    def _description(self, soup: BeautifulSoup) -> str | None:
        article = soup.select_one(".nas-article")
        if not article:
            return None
        text = self._clean_text(article.get_text("\n", strip=True))
        return text

    def _period_start(self, soup: BeautifulSoup) -> date | None:
        text = self._first_text(soup, ".page-info__attributes__period")
        if not text:
            return None
        match = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", text)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _booking_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        for anchor in soup.select('#購票資訊 a[href], a.c-btn-underline[href]'):
            href = anchor.get("href") or ""
            if "ticket.com.tw" in href or "UTK" in href:
                return urljoin(page_url, href)
        return None

    def _trailer_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        iframe = soup.select_one('iframe[src*="youtube.com"], iframe[src*="youtu.be"]')
        if iframe and iframe.get("src"):
            return urljoin(page_url, iframe["src"])
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            if "youtube.com" in href or "youtu.be" in href:
                return href
        return None

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

    def _first_text(self, soup: BeautifulSoup, selector: str) -> str | None:
        node = soup.select_one(selector)
        if not node:
            return None
        return self._clean_text(node.get_text(" ", strip=True))

    def _first_image_url(self, soup: BeautifulSoup, selector: str, page_url: str) -> str | None:
        urls = self._image_urls(soup, selector, page_url)
        return urls[0] if urls else None

    def _image_urls(self, soup: BeautifulSoup, selector: str, page_url: str) -> list[str]:
        urls: list[str] = []
        for image in soup.select(selector):
            src = image.get("data-src") or image.get("src")
            if not src:
                continue
            absolute = urljoin(page_url, src)
            if absolute not in urls:
                urls.append(absolute)
        return urls

    def _parse_time(self, value: str | None):
        if not value:
            return None
        match = re.search(r"(\d{1,2}):(\d{2})", value)
        if not match:
            return None
        return datetime.strptime(match.group(0), "%H:%M").time()

    def _runtime(self, value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"(\d{2,3})\s*min", value, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _rating_from_classes(self, soup: BeautifulSoup) -> str | None:
        grading = soup.select_one(".film-grading")
        if not grading:
            return None
        return self._rating(" ".join(grading.get("class") or []))

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.replace(" ", "")
        if "plus18" in text or "限制" in text or "18" in text:
            return "限制級"
        if "plus15" in text or "輔15" in text:
            return "輔15級"
        if "plus12" in text or "輔12" in text:
            return "輔12級"
        if "plus6" in text or "保護" in text or "6" in text:
            return "保護級"
        if "plus0" in text or "普遍" in text:
            return "普遍級"
        return value

    def _split_title(self, value: str | None) -> tuple[str | None, str | None]:
        text = self._clean_text(value)
        if not text:
            return None, None
        last_cjk = -1
        for index, char in enumerate(text):
            if "\u4e00" <= char <= "\u9fff":
                last_cjk = index
        if last_cjk < 0 or last_cjk == len(text) - 1:
            return text, None
        title_zh = text[: last_cjk + 1].strip()
        title_en = text[last_cjk + 1 :].strip()
        return title_zh or text, title_en or None

    def _source_movie_id(self, url: str) -> str:
        return url.rstrip("/").rsplit("/", 1)[-1]

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return re.sub(r"\s+", " ", value).strip() or None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
