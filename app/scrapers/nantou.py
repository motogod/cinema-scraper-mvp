from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.nantoutheater.com"
INDEX_URL = f"{SITE_BASE_URL}/index"
ORDER_URL = f"{SITE_BASE_URL}/movie_order"
CHAIN = "Nantou Theater"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="南投戲院",
    city="南投",
    address="南投縣南投市大同街87號",
    source_cinema_id="nantou-theater",
)


class NantouTheaterScraper:
    """Scraper for 南投戲院.

    Showtime pages are server-rendered by date. Movie detail pages provide the
    richer metadata used to fill movie records.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        index_soup = BeautifulSoup(self._fetch_text(INDEX_URL), "lxml")
        movie_options = self._movie_options(index_soup)
        movie_cache: dict[str, tuple[ScrapedMovie, str | None]] = {}
        results: list[ScrapedShowtime] = []

        for show_date in self._available_dates(index_soup):
            page_url = f"{ORDER_URL}?search_date={show_date.isoformat()}&search_time=0"
            soup = BeautifulSoup(self._fetch_text(page_url), "lxml")
            movie_options.update(self._movie_options(soup))
            for group in self._showtime_groups(soup, show_date):
                movie_id = group["movie_id"] or movie_options.get(group["title"])
                if not movie_id:
                    movie_id = self._movie_key(group["title"])
                if movie_id not in movie_cache:
                    movie_cache[movie_id] = self._movie_from_detail(movie_id, group["title"])
                movie, language = movie_cache[movie_id]
                group_date = group["show_date"] or show_date

                for start_time, booking_url, period_id in group["showtimes"]:
                    source_key = (
                        f"nantou:{movie.source_movie_id}:{period_id or ''}:"
                        f"{group_date.isoformat()}:{start_time.strftime('%H:%M')}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=group_date,
                            start_time=start_time,
                            hall_name=None,
                            format="數位",
                            language=language,
                            booking_url=booking_url,
                            source="nantou",
                            source_showtime_id=source_key,
                            version_label=self._version_label(language),
                            auditorium_brand=None,
                            projection_type="數位",
                            audio_language=language,
                            subtitle_language=None,
                            source_payload={
                                "order_url": page_url,
                                "movie_period_id": period_id,
                            },
                        )
                    )
        return self._dedupe(results)

    def _available_dates(self, soup: BeautifulSoup) -> list[date]:
        dates: list[date] = []
        for option in soup.select('select[name="search_date"] option[value]'):
            parsed = self._parse_date(option.get("value"))
            if parsed and parsed not in dates:
                dates.append(parsed)
        return dates

    def _movie_options(self, soup: BeautifulSoup) -> dict[str, str]:
        options: dict[str, str] = {}
        for option in soup.select('select[name="search_movie_id"] option[value]'):
            movie_id = (option.get("value") or "").strip()
            title = self._clean_text(option.get_text(" ", strip=True))
            if movie_id and title and title != "全部電影":
                options[title] = movie_id
        return options

    def _showtime_groups(self, soup: BeautifulSoup, fallback_date: date) -> list[dict]:
        groups: list[dict] = []
        headings = soup.find_all("h4", string=re.compile(r"\(\s*\d{4}-\d{2}-\d{2}\s*\)"))
        for heading in headings:
            title, show_date = self._parse_group_heading(heading.get_text(" ", strip=True))
            if not title:
                continue
            show_date = show_date or fallback_date
            showtimes = []
            for sibling in heading.find_next_siblings():
                if sibling.name == "h4":
                    break
                if sibling.name != "a":
                    continue
                start_time = self._parse_time(sibling.get_text(" ", strip=True))
                if not start_time:
                    continue
                href = sibling.get("href") or ""
                booking_url = urljoin(SITE_BASE_URL, href)
                showtimes.append((start_time, booking_url, self._period_id(href)))
            if showtimes:
                groups.append(
                    {
                        "title": title,
                        "show_date": show_date,
                        "movie_id": None,
                        "showtimes": showtimes,
                    }
                )
        return groups

    def _movie_from_detail(
        self, movie_id: str, fallback_title: str | None
    ) -> tuple[ScrapedMovie, str | None]:
        detail_url = f"{SITE_BASE_URL}/movie/{movie_id}" if movie_id.isdigit() else None
        if not detail_url:
            return (
                ScrapedMovie(
                    title=fallback_title or movie_id,
                    title_zh=fallback_title,
                    detail_url=ORDER_URL,
                    source_movie_id=movie_id,
                ),
                None,
            )
        try:
            soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
        except Exception:
            return (
                ScrapedMovie(
                    title=fallback_title or movie_id,
                    title_zh=fallback_title,
                    detail_url=detail_url,
                    source_movie_id=movie_id,
                ),
                None,
            )

        title = self._first_text(soup, "h2 strong") or fallback_title or movie_id
        category_line = self._first_text(soup, "p.pb-2")
        category, language, rating = self._category_language_rating(category_line)
        return (
            ScrapedMovie(
                title=title,
                title_zh=title,
                poster_url=self._first_image_url(soup, detail_url),
                release_date=self._release_date(soup),
                rating=rating,
                genre=category,
                description=self._description(soup),
                director=self._label_value(soup, "導演"),
                cast=self._label_value(soup, "演員"),
                trailer_url=self._trailer_url(soup, detail_url),
                detail_url=detail_url,
                source_movie_id=movie_id,
            ),
            language,
        )

    def _parse_group_heading(self, value: str) -> tuple[str | None, date | None]:
        match = re.match(r"(?P<title>.*?)\s*\(\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\)", value)
        if not match:
            return self._clean_text(value), None
        return self._clean_text(match.group("title")), self._parse_date(match.group("date"))

    def _category_language_rating(self, value: str | None) -> tuple[str | None, str | None, str | None]:
        parts = [self._clean_text(part) for part in (value or "").split("/")]
        parts = [part for part in parts if part]
        category = parts[0] if len(parts) >= 1 else None
        language = parts[1] if len(parts) >= 2 else None
        rating = self._rating(parts[2]) if len(parts) >= 3 else None
        return category, language, rating

    def _rating(self, value: str | None) -> str | None:
        text = self._clean_text(value) or ""
        mapping = {
            "普遍級": "普遍級",
            "保護級": "保護級",
            "輔12級": "輔12級",
            "輔15級": "輔15級",
            "限制級": "限制級",
        }
        for key, rating in mapping.items():
            if key in text:
                return rating
        return text or None

    def _description(self, soup: BeautifulSoup) -> str | None:
        label = soup.find(string=re.compile(r"劇情介紹"))
        if not label:
            return None
        paragraph = label.find_parent().find_next_sibling("p") if label.find_parent() else None
        return self._clean_text(paragraph.get_text("\n", strip=True)) if paragraph else None

    def _label_value(self, soup: BeautifulSoup, label: str) -> str | None:
        for strong in soup.find_all("strong"):
            text = self._clean_text(strong.get_text(" ", strip=True)) or ""
            if label not in text:
                continue
            parent = strong.find_parent()
            if not parent:
                continue
            value = parent.get_text(" ", strip=True)
            value = re.sub(rf"^{re.escape(label)}\s*[：:]\s*", "", value).strip()
            return value or None
        return None

    def _release_date(self, soup: BeautifulSoup) -> date | None:
        value = self._label_value(soup, "上映日期")
        return self._parse_date(value)

    def _version_label(self, language: str | None) -> str:
        return f"數位({language})" if language else "數位"

    def _period_id(self, href: str | None) -> str | None:
        query = parse_qs(urlparse(href or "").query)
        values = query.get("search_movieperiod_id")
        return values[0] if values else None

    def _parse_date(self, value: str | None) -> date | None:
        match = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
        if not match:
            return None
        return datetime.strptime(match.group(0), "%Y-%m-%d").date()

    def _parse_time(self, value: str | None):
        match = re.search(r"(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)", value or "")
        if not match:
            return None
        hour = int(match.group("hour"))
        if hour > 23:
            return None
        return datetime.strptime(f"{hour:02d}:{match.group('minute')}", "%H:%M").time()

    def _first_image_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        image = soup.select_one("img.img-fluid[src]")
        return urljoin(base_url, image.get("src") or "") if image else None

    def _trailer_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        iframe = soup.select_one("iframe[src]")
        return urljoin(base_url, iframe.get("src") or "") if iframe else None

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

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
        return text or None

    def _movie_key(self, title: str | None) -> str:
        if not title:
            return ""
        return re.sub(r"[\W_]+", "", title).lower()

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
