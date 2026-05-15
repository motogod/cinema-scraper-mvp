from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.miranewcinemas.com"
TIMETABLE_URL = f"{SITE_BASE_URL}/Booking/Timetable"
CHAIN = "Miranew Cinemas"

CINEMA_ADDRESS_BY_ID = {
    "1004": "桃園市蘆竹區南崁路一段112號7樓",
    "1005": "台北市中山區樂群三路200號",
}


class MiranewScraper:
    """Scraper for Miranew Cinemas.

    The timetable page embeds a JavaScript `CinemaList` JSON payload. It
    contains cinema groups, movies, show dates, hall labels, and session ids.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        payload = self._fetch_timetable_payload()
        results: list[ScrapedShowtime] = []
        for cinema_payload in payload.get("Data", {}).get("CinemaGroup", []):
            cinema = self._cinema_from_payload(cinema_payload)
            for movie_payload in cinema_payload.get("MovieInfo") or []:
                movie = self._movie_from_payload(movie_payload)
                for show_date_payload in movie_payload.get("ShowDateList") or []:
                    show_date = self._parse_date(show_date_payload.get("ShowDateISO"))
                    if not show_date:
                        continue
                    for showtime_group in show_date_payload.get("ShowTimeList") or []:
                        format_info = self._format_info(
                            showtime_group.get("MovieHallCht"),
                            showtime_group.get("MovieHallEn"),
                        )
                        for session in showtime_group.get("SessionList") or []:
                            start_time = self._parse_time(session.get("ShowTime"))
                            if not start_time:
                                continue
                            session_id = str(session.get("SessionId") or "")
                            source_key = (
                                f"miranew:{cinema.source_cinema_id}:{session_id}:"
                                f"{show_date.isoformat()}:{movie.source_movie_id or movie.title}"
                            )
                            results.append(
                                ScrapedShowtime(
                                    cinema=cinema,
                                    movie=movie,
                                    show_date=show_date,
                                    start_time=start_time,
                                    hall_name=self._hall_name(session.get("MovieHallCode")),
                                    format=format_info["format"],
                                    language=format_info["language"],
                                    booking_url=self._booking_url(
                                        cinema.source_cinema_id,
                                        session_id,
                                        movie.title,
                                    ),
                                    source="miranew",
                                    source_showtime_id=source_key,
                                    version_label=format_info["version_label"],
                                    auditorium_brand=format_info["auditorium_brand"],
                                    projection_type=format_info["projection_type"],
                                    audio_language=format_info["language"],
                                    subtitle_language=None,
                                    source_payload={
                                        "cinema": {
                                            "id": cinema_payload.get("CinemaId"),
                                            "name": cinema_payload.get("CinemaCName"),
                                        },
                                        "movie": {
                                            "post_url": movie_payload.get("PostUrl"),
                                            "name": movie_payload.get("MovieCName"),
                                        },
                                        "showtime_group": showtime_group,
                                        "session": session,
                                    },
                                )
                            )
        return self._dedupe(results)

    def _fetch_timetable_payload(self) -> dict:
        html = self._fetch_text(TIMETABLE_URL)
        match = re.search(r"var CinemaList = '(?P<payload>.*?)';", html, re.DOTALL)
        if not match:
            raise RuntimeError("Could not find Miranew CinemaList payload")
        payload_text = match.group("payload").replace(r"\"", '"').replace(r"\/", "/")
        return json.loads(payload_text)

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
            return response.read().decode("utf-8")

    def _cinema_from_payload(self, payload: dict) -> ScrapedCinema:
        cinema_id = str(payload.get("CinemaId") or "")
        address = CINEMA_ADDRESS_BY_ID.get(cinema_id)
        name = payload.get("CinemaCName") or f"Miranew Cinemas {cinema_id}"
        return ScrapedCinema(
            chain=CHAIN,
            name=name,
            city=self._city_from_address(address) or self._city_from_name(name),
            address=address,
            source_cinema_id=cinema_id or None,
        )

    def _movie_from_payload(self, payload: dict) -> ScrapedMovie:
        title_zh, rating_from_title = self._split_title_rating(payload.get("MovieCName"))
        title_en, rating_from_en = self._split_title_rating(payload.get("MovieEName"))
        rating = self._rating(payload.get("Rate")) or rating_from_title or rating_from_en
        post_url = payload.get("PostUrl")
        return ScrapedMovie(
            title=title_zh or title_en or f"Miranew Movie {post_url}",
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=self._poster_url(post_url),
            duration_minutes=self._parse_int(payload.get("MovieLength")),
            rating=rating,
            source_movie_id=post_url or self._movie_key(title_zh or title_en),
        )

    def _format_info(
        self,
        hall_zh: str | None,
        hall_en: str | None,
    ) -> dict[str, str | None]:
        label = self._clean_text(hall_zh) or self._clean_text(hall_en) or ""
        language = self._language(label) or self._language(hall_en)

        auditorium_brand = None
        upper = f"{label} {hall_en or ''}".upper()
        if "IMAX" in upper:
            auditorium_brand = "IMAX"
        elif "皇家" in label or "ROYAL" in upper:
            auditorium_brand = "皇家影城"

        projection_type = None
        if "3D" in upper:
            projection_type = "3D"
        elif label:
            projection_type = "數位"

        format_label = label
        for token in ["英文版", "日文版", "中文版", "國語版"]:
            format_label = format_label.replace(token, "").strip()
        return {
            "format": format_label or None,
            "language": language,
            "version_label": label or None,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
        }

    def _booking_url(
        self,
        cinema_id: str | None,
        session_id: str | None,
        movie_name: str | None,
    ) -> str | None:
        if not cinema_id or not session_id:
            return TIMETABLE_URL
        url = f"{SITE_BASE_URL}/Booking/booking_select?cid={cinema_id}&sid={session_id}"
        if movie_name:
            url += f"&m_name={quote(movie_name)}"
        return url

    def _poster_url(self, post_url: str | None) -> str | None:
        if not post_url:
            return None
        if post_url.startswith("http"):
            return post_url
        return f"{SITE_BASE_URL}/MiramarApp/Resource/{post_url}_S.jpg"

    def _split_title_rating(self, value: str | None) -> tuple[str | None, str | None]:
        text = self._clean_text(value)
        if not text:
            return None, None
        match = re.search(r"\((?P<rating>[^()]+)\)\s*$", text)
        if not match:
            return text, None
        title = text[: match.start()].strip()
        return title or text, self._rating(match.group("rating"))

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip().upper()
        mapping = {
            "G": "普遍級",
            "P": "保護級",
            "PG": "輔導級",
            "PG-12": "輔12級",
            "PG-15": "輔15級",
            "R": "限制級",
            "普": "普遍級",
            "護": "保護級",
            "限": "限制級",
            "輔12級": "輔12級",
            "輔15級": "輔15級",
        }
        return mapping.get(text, value.strip())

    def _language(self, value: str | None) -> str | None:
        text = value or ""
        upper = text.upper()
        if "英文" in text or " EN" in upper or "ENG" in upper:
            return "英語"
        if "日文" in text or " JP" in upper or "JPN" in upper:
            return "日語"
        if "中文" in text or "國語" in text or " CH" in upper:
            return "國語"
        if "韓文" in text or " KR" in upper or "KOR" in upper:
            return "韓語"
        return None

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None

    def _parse_time(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return None

    def _parse_int(self, value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _hall_name(self, value: str | None) -> str | None:
        if not value:
            return None
        if value.isdigit():
            return f"{value}廳"
        return value

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
        if not name:
            return None
        if "台北" in name or "大直" in name:
            return "台北"
        if "桃園" in name or "台茂" in name:
            return "桃園"
        return None

    def _movie_key(self, value: str | None) -> str | None:
        if not value:
            return None
        return re.sub(r"[：:：－—\-・·\s　！!？?（）()《》「」『』,.，。/\\]+", "", value).lower()

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
