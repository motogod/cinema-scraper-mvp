from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.cm-movie.com.tw"
SHOWTIME_URL = f"{SITE_BASE_URL}/category/time/"
SOURCE = "cm_movie"
CHAIN = "今日全美戲院"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="今日全美戲院",
    city="台南",
    address="台南市中西區永福路二段187號 / 台南市中西區中正路249號",
    source_cinema_id="cm-movie",
)


class CmMovieScraper:
    """Scraper for 今日全美戲院 showtime posts."""

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SHOWTIME_URL), "lxml")
        post_links = self._post_links(soup)
        results: list[ScrapedShowtime] = []

        for post_url in post_links:
            post_soup = BeautifulSoup(self._fetch_text(post_url), "lxml")
            movie = self._movie_from_post(post_soup, post_url)
            if not movie:
                continue
            language = self._language(post_soup)
            version_label = self._version_label(language)
            for show_date, start_time in self._showtimes_from_post(post_soup):
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
                        format="數位",
                        language=language,
                        booking_url=post_url,
                        source=SOURCE,
                        source_showtime_id=source_showtime_id,
                        version_label=version_label,
                        projection_type="數位",
                        audio_language=language,
                        source_payload={
                            "source_page": post_url,
                        },
                    )
                )

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("cm_movie scraper found no showtimes; keeping existing data")
        return results

    def _post_links(self, soup: BeautifulSoup) -> list[str]:
        links: list[str] = []
        for link in soup.select("article h2.entry-title a[href]"):
            href = link.get("href")
            if href:
                links.append(urljoin(SITE_BASE_URL, href))
        return list(dict.fromkeys(links))

    def _movie_from_post(self, soup: BeautifulSoup, post_url: str) -> ScrapedMovie | None:
        title = self._first_text(soup, "h1.entry-title")
        if not title:
            return None
        return ScrapedMovie(
            title=title,
            title_zh=title,
            poster_url=self._poster_url(soup, post_url),
            rating=self._rating(soup),
            release_date=self._release_date(soup),
            duration_minutes=self._duration_minutes(soup),
            director=self._label_value(soup, "導演"),
            cast=self._label_value(soup, "演員"),
            detail_url=post_url,
            source_movie_id=self._source_movie_id(post_url),
        )

    def _showtimes_from_post(self, soup: BeautifulSoup) -> list[tuple[date, datetime.time]]:
        output: list[tuple[date, datetime.time]] = []
        year = date.today().year
        for line in self._content_lines(soup):
            if "公休" in line:
                continue
            times = self._times(line)
            if not times:
                continue
            for show_date in self._dates(line, year):
                for start_time in times:
                    output.append((show_date, start_time))
        return output

    def _content_lines(self, soup: BeautifulSoup) -> list[str]:
        content = soup.select_one("section.entry-content")
        if not content:
            return []
        lines: list[str] = []
        for node in content.find_all(["p", "li"], recursive=True):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                lines.append(text)
        return lines

    def _dates(self, line: str, year: int) -> list[date]:
        text = line.split(self._times(line)[0].strftime("%H:%M"), 1)[0]
        text = text.replace("月", "/").replace("日", "")

        range_match = re.search(
            r"(?P<sm>\d{1,2})/(?P<sd>\d{1,2})\s*(?:至|到|~|-)\s*"
            r"(?:(?P<em>\d{1,2})/)?(?P<ed>\d{1,2})",
            text,
        )
        if range_match:
            start = date(year, int(range_match.group("sm")), int(range_match.group("sd")))
            end_month = int(range_match.group("em") or range_match.group("sm"))
            end = date(year, end_month, int(range_match.group("ed")))
            if end < start:
                end = date(year + 1, end.month, end.day)
            days = (end - start).days
            return [start + timedelta(days=offset) for offset in range(days + 1)]

        dates: list[date] = []
        current_month: int | None = None
        date_part = re.split(r"\d{1,2}[:：]\d{2}", text, maxsplit=1)[0]
        for token in re.split(r"[、,，\s]+", date_part):
            token = token.strip()
            if not token:
                continue
            full_match = re.fullmatch(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})", token)
            if full_match:
                current_month = int(full_match.group("month"))
                dates.append(date(year, current_month, int(full_match.group("day"))))
                continue
            day_match = re.fullmatch(r"\d{1,2}", token)
            if day_match and current_month:
                dates.append(date(year, current_month, int(token)))
        return dates

    def _times(self, line: str) -> list[datetime.time]:
        times: list[datetime.time] = []
        for hour, minute in re.findall(r"(\d{1,2})[:：](\d{2})", line):
            hour_int = int(hour)
            minute_int = int(minute)
            if hour_int > 23 or minute_int > 59:
                continue
            times.append(datetime.strptime(f"{hour_int:02d}:{minute_int:02d}", "%H:%M").time())
        return times

    def _language(self, soup: BeautifulSoup) -> str | None:
        value = self._label_value(soup, "語言")
        if value:
            return value
        value = self._label_value(soup, "語")
        return value

    def _rating(self, soup: BeautifulSoup) -> str | None:
        explicit = self._label_value(soup, "級別")
        if explicit:
            return explicit
        text = self._clean_text(soup.get_text(" ", strip=True)) or ""
        match = re.search(r"(普遍級|保護級|輔12級|輔15級|限制級)", text)
        return match.group(1) if match else None

    def _release_date(self, soup: BeautifulSoup) -> date | None:
        value = self._label_value(soup, "上映日期")
        if not value:
            return None
        match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", value)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _duration_minutes(self, soup: BeautifulSoup) -> int | None:
        value = self._label_value(soup, "片長")
        text = self._clean_text(value) or ""
        match = re.search(r"(?:(\d+)\s*(?:時|小時))?\s*(\d+)\s*分", text)
        if not match:
            return None
        return int(match.group(1) or 0) * 60 + int(match.group(2))

    def _label_value(self, soup: BeautifulSoup, label: str) -> str | None:
        label_key = self._label_key(label)
        for line in self._content_lines(soup):
            key, separator, value = line.partition("：")
            if not separator:
                key, separator, value = line.partition(":")
            if not separator:
                continue
            if self._label_key(key).startswith(label_key):
                return self._clean_text(value)
        return None

    def _label_key(self, value: str | None) -> str:
        return re.sub(r"[\s　：:、,，]+", "", value or "")

    def _version_label(self, language: str | None) -> str:
        return f"數位 / {language}" if language else "數位"

    def _poster_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        image = soup.select_one("section.entry-content img[src]")
        return urljoin(base_url, image.get("src") or "") if image else None

    def _source_movie_id(self, post_url: str) -> str | None:
        path = urlparse(post_url).path.strip("/")
        return path or None

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

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text or None
