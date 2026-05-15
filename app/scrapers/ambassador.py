from __future__ import annotations

import json
import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.ambassador.com.tw"
BOOKING_URL = "https://booking.ambassador.com.tw/"
CHAIN = "Ambassador Theatres"


class AmbassadorScraper:
    """Scraper for Ambassador Theatres.

    Ambassador exposes current movie ids on the home page. For each movie, the
    site returns valid screening dates from `/Home/GetJsonWithDate`, and each
    movie/date page contains rendered theater showtimes.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for movie_id, fallback_title in self._movie_options():
            for show_date in self._screening_dates(movie_id):
                try:
                    html = self._fetch_text(self._movie_url(movie_id, show_date))
                    results.extend(self._parse_movie_page(html, movie_id, fallback_title, show_date))
                except Exception:
                    continue
        return self._dedupe(results)

    def _movie_options(self) -> list[tuple[str, str]]:
        soup = BeautifulSoup(self._fetch_text(SITE_BASE_URL), "lxml")
        movies: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in soup.select("#moveList li[data-id], #moveList_M option[value]"):
            movie_id = (item.get("data-id") or item.get("value") or "").strip()
            title = self._clean_text(item.get_text(" ", strip=True))
            if not movie_id or movie_id == "-1" or movie_id in seen or not title:
                continue
            seen.add(movie_id)
            movies.append((movie_id, title))
        return movies

    def _screening_dates(self, movie_id: str) -> list[date]:
        url = f"{SITE_BASE_URL}/Home/GetJsonWithDate?{urlencode({'MID': movie_id})}"
        payload = json.loads(self._fetch_text(url, accept="application/json"))
        dates: list[date] = []
        for item in payload:
            parsed = self._parse_date(item.get("ScreeningDate"))
            if parsed:
                dates.append(parsed)
        return dates

    def _parse_movie_page(
        self,
        html: str,
        movie_id: str,
        fallback_title: str,
        show_date: date,
    ) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(html, "lxml")
        movie = self._movie_from_page(soup, movie_id, fallback_title)

        results: list[ScrapedShowtime] = []
        for theater_box in soup.select(".theater-box"):
            cinema = self._cinema_from_box(theater_box)
            if not cinema:
                continue

            current_format = None
            for child in theater_box.children:
                if not getattr(child, "name", None):
                    continue
                classes = child.get("class") or []
                if child.name == "p" and "tag-seat" in classes:
                    current_format = self._format_info(child.get_text(" ", strip=True))
                    continue
                if child.name != "ul" or "seat-list" not in classes:
                    continue

                format_info = current_format or self._format_info("")
                for item in child.select("li"):
                    time_label = self._clean_text(item.select_one("h6").get_text(" ", strip=True) if item.select_one("h6") else "")
                    start_time = self._parse_time(time_label)
                    if not start_time:
                        continue
                    hall_name = self._hall_name(item.select_one(".info").get_text(" ", strip=True) if item.select_one(".info") else None)
                    seat_brand = self._seat_brand(item)
                    auditorium_brand = seat_brand or format_info["auditorium_brand"]
                    source_key = (
                        f"ambassador:{movie_id}:{cinema.source_cinema_id}:"
                        f"{show_date.isoformat()}:{time_label}:{hall_name or ''}:{format_info['version_label'] or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=cinema,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=hall_name,
                            format=format_info["format"],
                            language=format_info["language"],
                            booking_url=BOOKING_URL,
                            source="ambassador",
                            source_showtime_id=source_key,
                            version_label=format_info["version_label"],
                            auditorium_brand=auditorium_brand,
                            projection_type=format_info["projection_type"],
                            audio_language=format_info["language"],
                            subtitle_language=None,
                            source_payload={
                                "movie_id": movie_id,
                                "cinema_id": cinema.source_cinema_id,
                                "time_label": time_label,
                                "format_label": format_info["raw_label"],
                            },
                        )
                    )
        return results

    def _movie_from_page(self, soup: BeautifulSoup, movie_id: str, fallback_title: str) -> ScrapedMovie:
        info = soup.select_one(".movie-info-box")
        title_zh = self._clean_text(info.select_one("h2").get_text(" ", strip=True) if info and info.select_one("h2") else fallback_title)
        title_en = self._clean_text(info.select_one("h6").get_text(" ", strip=True) if info and info.select_one("h6") else None)
        poster = soup.select_one(".movie-pic-box img")
        trailer = soup.select_one(".movie-play iframe")
        rating = self._clean_text(info.select_one(".rating-box .tag-rating-p").get_text(" ", strip=True) if info and info.select_one(".rating-box .tag-rating-p") else None)
        duration_text = self._clean_text(info.select_one(".rating-box span:last-child").get_text(" ", strip=True) if info and info.select_one(".rating-box span:last-child") else None)

        description = None
        cast = None
        genre = None
        release_date = None
        if info:
            for paragraph in info.select("p"):
                text = self._clean_text(paragraph.get_text(" ", strip=True))
                if not text:
                    continue
                if text.startswith("主要演員："):
                    cast = text.removeprefix("主要演員：").strip() or None
                elif text.startswith("影片類型："):
                    genre = text.removeprefix("影片類型：").strip() or None
                elif text.startswith("上映日期："):
                    release_date = self._parse_date(text.removeprefix("上映日期：").strip())
                elif "note" not in (paragraph.get("class") or []):
                    description = text

        still_urls = [
            urljoin(SITE_BASE_URL, image.get("src"))
            for image in soup.select(".more-pics img[src]")
            if image.get("src")
        ]

        return ScrapedMovie(
            title=title_zh or fallback_title,
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=urljoin(SITE_BASE_URL, poster.get("src")) if poster and poster.get("src") else None,
            still_urls=still_urls or None,
            release_date=release_date,
            duration_minutes=self._duration_minutes(duration_text),
            rating=rating,
            genre=genre,
            description=description,
            cast=cast,
            trailer_url=trailer.get("src") if trailer and trailer.get("src") else None,
            detail_url=self._movie_url(movie_id, date.today()),
            source_movie_id=movie_id,
        )

    def _cinema_from_box(self, theater_box) -> ScrapedCinema | None:
        link = theater_box.select_one("h3 a[href]")
        if not link:
            return None
        name = self._clean_text(link.get_text(" ", strip=True))
        href = link.get("href") or ""
        cinema_id = parse_qs(urlparse(href).query).get("ID", [None])[0]
        spans = [
            self._clean_text(span.get_text(" ", strip=True))
            for span in theater_box.select("h3 span")
        ]
        address = next((span for span in spans if span and span != "|" and not span.startswith("(")), None)
        return ScrapedCinema(
            chain=CHAIN,
            name=name or f"Ambassador {cinema_id}",
            city=self._city_from_address(address) or self._city_from_name(name),
            address=address,
            source_cinema_id=cinema_id,
        )

    def _format_info(self, label: str) -> dict[str, str | None]:
        raw_label = self._clean_text(label)
        match = re.match(r"^\((?P<version>[^)]+)\)", raw_label or "")
        version_label = match.group("version") if match else raw_label
        parts = [part.strip() for part in re.split(r"[‧・/]", version_label or "") if part.strip()]

        language = None
        for part in parts:
            language = self._language(part) or language

        auditorium_brand = None
        for part in parts:
            upper = part.upper()
            if "ATMOS" in upper:
                auditorium_brand = "ATMOS"
            elif "金鑽" in part:
                auditorium_brand = "金鑽貴賓廳"
            elif "D-BOX" in upper or "DBOX" in upper:
                auditorium_brand = "D-BOX"

        projection_type = None
        for part in parts:
            upper = part.upper()
            if "3D" in upper:
                projection_type = "3D"
            elif "2D" in upper or "數位" in part:
                projection_type = "數位"

        format_parts = [part for part in parts if not self._language(part)]
        return {
            "raw_label": raw_label,
            "version_label": version_label,
            "format": "‧".join(format_parts) or None,
            "language": language,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
        }

    def _fetch_text(self, url: str, accept: str = "text/html") -> str:
        request = Request(
            url,
            headers={
                "Accept": accept,
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": SITE_BASE_URL,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        )
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")

    def _movie_url(self, movie_id: str, show_date: date) -> str:
        return f"{SITE_BASE_URL}/home/MovieContent?{urlencode({'MID': movie_id, 'DT': show_date.strftime('%Y/%m/%d')})}"

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for pattern in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), pattern).date()
            except ValueError:
                continue
        return None

    def _parse_time(self, value: str | None):
        if not value:
            return None
        match = re.search(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", value)
        if not match:
            return None
        return datetime.strptime(match.group(0), "%H:%M").time()

    def _duration_minutes(self, value: str | None) -> int | None:
        if not value:
            return None
        hours = re.search(r"(\d+)\s*時", value)
        minutes = re.search(r"(\d+)\s*分", value)
        total = 0
        if hours:
            total += int(hours.group(1)) * 60
        if minutes:
            total += int(minutes.group(1))
        return total or None

    def _hall_name(self, value: str | None) -> str | None:
        if not value:
            return None
        return re.sub(r"\s*\d+\s*席.*$", "", value).strip() or None

    def _seat_brand(self, item) -> str | None:
        text = " ".join(
            value
            for value in [
                item.get_text(" ", strip=True),
                " ".join(img.get("src") or "" for img in item.select("img")),
                " ".join(span.get("title") or "" for span in item.select("[title]")),
            ]
            if value
        ).upper()
        if "D-BOX" in text or "DBOX" in text:
            return "D-BOX"
        if "尊爵" in text or "PRIME" in text:
            return "尊爵席"
        return None

    def _language(self, value: str | None) -> str | None:
        text = value or ""
        if "英文" in text or "英語" in text:
            return "英語"
        if "國語" in text or "中文版" in text or "中文" in text:
            return "國語"
        if "日文" in text or "日語" in text:
            return "日語"
        if "韓文" in text or "韓語" in text:
            return "韓語"
        if "粵語" in text or "粵語" in text:
            return "粵語"
        return None

    def _city_from_address(self, address: str | None) -> str | None:
        if not address:
            return None
        match = re.match(r"(.{2,3}[市縣])", address)
        if not match:
            return None
        return {
            "台北市": "台北",
            "臺北市": "台北",
            "新北市": "新北",
            "桃園市": "桃園",
            "新竹市": "新竹",
            "新竹縣": "新竹",
            "苗栗縣": "苗栗",
            "台中市": "台中",
            "臺中市": "台中",
            "彰化縣": "彰化",
            "南投縣": "南投",
            "雲林縣": "雲林",
            "嘉義市": "嘉義",
            "嘉義縣": "嘉義",
            "台南市": "台南",
            "臺南市": "台南",
            "高雄市": "高雄",
            "屏東市": "屏東",
            "屏東縣": "屏東",
            "宜蘭縣": "宜蘭",
            "花蓮市": "花蓮",
            "花蓮縣": "花蓮",
            "台東市": "台東",
            "臺東市": "台東",
            "台東縣": "台東",
            "臺東縣": "台東",
            "澎湖縣": "澎湖",
            "金門縣": "金門",
        }.get(match.group(1), match.group(1).removesuffix("市").removesuffix("縣"))

    def _city_from_name(self, name: str | None) -> str | None:
        for city in ["台北", "新北", "桃園", "台南", "高雄", "屏東", "金門"]:
            if name and city in name:
                return city
        if name and any(token in name for token in ["林口", "淡水", "新莊"]):
            return "新北"
        if name and "八德" in name:
            return "桃園"
        return None

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
