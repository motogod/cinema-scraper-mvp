from __future__ import annotations

import http.cookiejar
import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.uch-movies.tw"
TIME_URL = f"{SITE_BASE_URL}/time.aspx"
SOURCE = "uch"
CHAIN = "Universal Chunghwa Cinemas"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="環球中華影城",
    city="雲林",
    address="雲林縣斗六市雲林路二段19號",
    source_cinema_id="uch-douliu",
)


class UchScraper:
    """Scraper for 雲林斗六環球中華影城."""

    def __init__(self):
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(cookie_jar))

    def scrape(self) -> list[ScrapedShowtime]:
        index_html = self._fetch_text(TIME_URL)
        index_soup = BeautifulSoup(index_html, "lxml")
        movie_cache: dict[str, ScrapedMovie] = {}
        results: list[ScrapedShowtime] = []

        for show_date in self._available_dates(index_soup):
            page_html = self._fetch_time_page(show_date)
            soup = BeautifulSoup(page_html, "lxml")
            for block in soup.select(".time_box"):
                movie = self._movie_from_time_block(block)
                if not movie:
                    continue
                cache_key = movie.source_movie_id or movie.title
                if cache_key not in movie_cache:
                    detail_movie = self._movie_from_detail(movie.detail_url, movie)
                    movie_cache[cache_key] = detail_movie or movie
                movie = movie_cache[cache_key]

                for hall_name, start_time in self._hall_showtimes(block):
                    source_showtime_id = (
                        f"{SOURCE}:{movie.source_movie_id or movie.title}:"
                        f"{show_date.isoformat()}:{start_time.strftime('%H:%M')}:"
                        f"{hall_name or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=hall_name,
                            format="數位",
                            language=self._language_from_title(movie.title),
                            booking_url="https://booking.uch-movies.tw/",
                            source=SOURCE,
                            source_showtime_id=source_showtime_id,
                            version_label=self._version_label(movie.title),
                            auditorium_brand=None,
                            projection_type="數位",
                            audio_language=self._language_from_title(movie.title),
                            subtitle_language=self._subtitle_from_title(movie.title),
                            source_payload={
                                "time_url": f"{TIME_URL}?date={show_date.isoformat()}",
                                "detail_url": movie.detail_url,
                            },
                        )
                    )

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("uch scraper found no showtimes; keeping existing data")
        return results

    def _available_dates(self, soup: BeautifulSoup) -> list[date]:
        dates: list[date] = []
        for option in soup.select("#DropDownList1 option[value]"):
            parsed = self._parse_date(option.get("value"))
            if parsed and parsed not in dates:
                dates.append(parsed)
        return dates

    def _fetch_time_page(self, show_date: date) -> str:
        html = self._fetch_text(TIME_URL)
        soup = BeautifulSoup(html, "lxml")
        fields = {
            node.get("name"): node.get("value", "")
            for node in soup.select("input[name]")
            if node.get("name")
        }
        fields["__EVENTTARGET"] = "DropDownList1"
        fields["__EVENTARGUMENT"] = ""
        fields["DropDownList1"] = show_date.isoformat()
        return self._fetch_text(
            f"{TIME_URL}?date={show_date.isoformat()}",
            data=urlencode(fields).encode(),
        )

    def _movie_from_time_block(self, block) -> ScrapedMovie | None:
        link = block.select_one(".movie_title a[href]")
        title = self._clean_text(link.get_text(" ", strip=True) if link else None)
        if not title:
            return None
        detail_url = urljoin(SITE_BASE_URL, link.get("href")) if link else None
        return ScrapedMovie(
            title=title,
            title_zh=self._clean_title(title),
            title_en=self._first_text(block, ".movie_title_e"),
            original_title=self._first_text(block, ".movie_title_e"),
            poster_url=self._poster_url(block, TIME_URL),
            duration_minutes=self._duration_minutes(block.get_text(" ", strip=True)),
            rating=self._rating_from_block(block),
            trailer_url=self._trailer_url(block),
            detail_url=detail_url,
            source_movie_id=self._source_movie_id(detail_url),
        )

    def _movie_from_detail(
        self,
        detail_url: str | None,
        fallback: ScrapedMovie,
    ) -> ScrapedMovie | None:
        if not detail_url:
            return None
        try:
            soup = BeautifulSoup(self._fetch_text(detail_url), "lxml")
        except Exception:
            return None

        title = self._first_text(soup, ".movie_title") or fallback.title
        original_title = self._first_text(soup, ".movie_title_e") or fallback.original_title
        info_text = self._label_text(soup)
        return ScrapedMovie(
            title=title,
            title_zh=self._clean_title(title),
            title_en=original_title,
            original_title=original_title,
            poster_url=self._poster_url(soup, detail_url) or fallback.poster_url,
            release_date=self._parse_date(self._label_value(soup, "上映日期")),
            duration_minutes=fallback.duration_minutes,
            rating=self._rating_from_block(soup) or fallback.rating,
            genre=self._label_value_from_text(info_text, "類型"),
            description=self._description(soup),
            director=self._label_value_from_text(info_text, "導演"),
            cast=self._label_value_from_text(info_text, "演員"),
            trailer_url=self._trailer_url(soup) or fallback.trailer_url,
            detail_url=detail_url,
            source_movie_id=self._source_movie_id(detail_url),
        )

    def _hall_showtimes(self, block) -> list[tuple[str | None, datetime.time]]:
        results = []
        info = block.select_one(".time_info") or block
        current_hall = None
        for child in info.children:
            name = getattr(child, "name", None)
            if name is None:
                continue
            classes = set(child.get("class") or [])
            if "room_number" in classes:
                current_hall = self._clean_text(child.get_text(" ", strip=True))
                continue
            if "time_item" not in classes:
                continue
            for item in child.select("li"):
                start_time = self._parse_time(item.get_text(" ", strip=True))
                if start_time:
                    results.append((current_hall, start_time))
        return results

    def _label_text(self, soup: BeautifulSoup) -> str:
        label = soup.select_one("#Label1")
        return label.get_text("\n", strip=True) if label else ""

    def _label_value(self, soup: BeautifulSoup, label: str) -> str | None:
        text = soup.get_text("\n", strip=True)
        return self._label_value_from_text(text, label)

    def _label_value_from_text(self, text: str | None, label: str) -> str | None:
        match = re.search(rf"{re.escape(label)}[：:]\s*([^\n]+)", text or "")
        return self._clean_text(match.group(1)) if match else None

    def _description(self, soup: BeautifulSoup) -> str | None:
        editor = soup.select_one(".text_editor")
        if not editor:
            return None
        for iframe in editor.select("iframe"):
            iframe.extract()
        return self._clean_text(editor.get_text("\n", strip=True))

    def _poster_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        image = soup.select_one('img[src*="upload/movies/"]')
        return urljoin(base_url, image.get("src") or "") if image else None

    def _trailer_url(self, soup: BeautifulSoup) -> str | None:
        iframe = soup.select_one(".text_editor iframe[src], iframe[src]")
        if iframe:
            return iframe.get("src")
        trailer = soup.select_one("[video-url]")
        if trailer:
            return trailer.get("video-url")
        return None

    def _duration_minutes(self, value: str | None) -> int | None:
        match = re.search(r"(\d+)\s*時\s*(\d+)\s*分", value or "")
        if not match:
            return None
        return int(match.group(1)) * 60 + int(match.group(2))

    def _rating_from_block(self, block) -> str | None:
        image = block.select_one(".slevel_area img")
        alt = self._clean_text(image.get("alt") if image else None)
        if alt:
            return self._normalize_rating(alt)
        src = image.get("src") if image else ""
        match = re.search(r"l(\d+)\.png", src or "")
        if not match:
            return None
        return {
            "1": "普遍級",
            "2": "保護級",
            "3": "輔12級",
            "4": "輔15級",
            "5": "限制級",
        }.get(match.group(1))

    def _normalize_rating(self, value: str) -> str:
        if "15" in value:
            return "輔15級"
        if "12" in value:
            return "輔12級"
        return value.replace("+", "")

    def _language_from_title(self, title: str | None) -> str | None:
        text = title or ""
        if "中文發音" in text:
            return "中文"
        if "英文發音" in text:
            return "英語"
        if "日文發音" in text:
            return "日語"
        return None

    def _subtitle_from_title(self, title: str | None) -> str | None:
        text = title or ""
        if "中文字幕" in text:
            return "中文"
        return None

    def _version_label(self, title: str | None) -> str:
        language = self._language_from_title(title)
        subtitle = self._subtitle_from_title(title)
        if language and subtitle:
            return f"數位({language}/{subtitle}字幕)"
        if language:
            return f"數位({language})"
        return "數位"

    def _clean_title(self, title: str | None) -> str | None:
        text = self._clean_text(title)
        if not text:
            return None
        return re.sub(r"\s*\([^)]*(?:發音|字幕)[^)]*\)\s*$", "", text).strip() or text

    def _source_movie_id(self, detail_url: str | None) -> str | None:
        values = parse_qs(urlparse(detail_url or "").query).get("getId1")
        return values[0] if values else None

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(value.strip(), pattern).date()
            except ValueError:
                continue
        match = re.search(r"\d{4}[-/.]\d{2}[-/.]\d{2}", value)
        if not match:
            return None
        return self._parse_date(match.group(0).replace(".", "-").replace("/", "-"))

    def _parse_time(self, value: str | None):
        match = re.search(r"(\d{1,2}):(\d{2})", value or "")
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()

    def _fetch_text(self, url: str, data: bytes | None = None) -> str:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Origin"] = SITE_BASE_URL
            headers["Referer"] = TIME_URL
        request = Request(url, data=data, headers=headers)
        with self.opener.open(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _first_text(self, node, selector: str) -> str | None:
        found = node.select_one(selector)
        return self._clean_text(found.get_text(" ", strip=True)) if found else None

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
