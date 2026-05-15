from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from time import time
from urllib.request import Request, urlopen

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.skcinemas.com"
CHAIN = "Shin Kong Cinemas"

CINEMAS = {
    "1001": ScrapedCinema(
        chain=CHAIN,
        name="台北獅子林新光影城",
        city="台北",
        address="台北市西寧南路36號4~5樓",
        source_cinema_id="1001",
    ),
    "1005": ScrapedCinema(
        chain=CHAIN,
        name="台北天母新光影城",
        city="台北",
        address="台北市士林區忠誠路二段202號4樓",
        source_cinema_id="1005",
    ),
    "1004": ScrapedCinema(
        chain=CHAIN,
        name="桃園青埔新光影城",
        city="桃園",
        address="桃園市中壢區春德路107號",
        source_cinema_id="1004",
    ),
    "1003": ScrapedCinema(
        chain=CHAIN,
        name="台中中港新光影城",
        city="台中",
        address="台中市臺灣大道三段301號13-14樓",
        source_cinema_id="1003",
    ),
    "1002": ScrapedCinema(
        chain=CHAIN,
        name="台南西門新光影城",
        city="台南",
        address="台南市西門路一段658號7~9樓",
        source_cinema_id="1002",
    ),
}


class SKCinemasScraper:
    """Scraper for Shin Kong Cinemas.

    The site signs every API request with the same timestamp/DID/HMAC headers
    used by its Next.js frontend.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        movie_map = self._movie_map(self._post("/api/VistaDataV2/GetHomePageListForApps"))
        results: list[ScrapedShowtime] = []
        for cinema_id, cinema in CINEMAS.items():
            payload = self._post(
                "/api/VistaDataV2/GetSessionByCinemasIDForApp",
                {"CustomerID": "", "Mobile": "", "CinemasID": cinema_id},
            )
            sessions_payload = payload.get("data") or {}
            fallback_titles = {
                item.get("FilmNameID"): item.get("FilmName")
                for item in sessions_payload.get("SessionFilm") or []
            }
            for session in sessions_payload.get("Session") or []:
                show_at = self._parse_datetime(session.get("_showDate"))
                if not show_at:
                    continue
                movie_id = session.get("FilmNameID")
                movie = movie_map.get(movie_id) or ScrapedMovie(
                    title=fallback_titles.get(movie_id) or f"Shin Kong Movie {movie_id}",
                    title_zh=fallback_titles.get(movie_id),
                    source_movie_id=movie_id,
                )
                format_info = self._format_info(session.get("FilmType"))
                session_id = str(session.get("SessionID") or "")
                source_key = (
                    f"skcinemas:{cinema_id}:{session_id}:"
                    f"{show_at.isoformat()}:{movie_id or ''}"
                )
                results.append(
                    ScrapedShowtime(
                        cinema=cinema,
                        movie=movie,
                        show_date=show_at.date(),
                        start_time=show_at.time().replace(second=0, microsecond=0),
                        hall_name=session.get("ScreenName"),
                        format=format_info["format"],
                        language=format_info["language"],
                        booking_url=f"{SITE_BASE_URL}/sessions",
                        source="skcinemas",
                        source_showtime_id=source_key,
                        version_label=format_info["version_label"],
                        auditorium_brand=format_info["auditorium_brand"],
                        projection_type=format_info["projection_type"],
                        audio_language=format_info["language"],
                        subtitle_language=None,
                        source_payload=session,
                    )
                )
        return self._dedupe(results)

    def _post(self, path: str, body: dict | None = None) -> dict:
        payload = body or {"CustomerID": "", "Mobile": ""}
        timestamp = str(int(time() * 1000))
        did = str(uuid.uuid4())
        request = Request(
            f"{SITE_BASE_URL}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/json",
                "DID": did,
                "timestamp": timestamp,
                "token": self._security_hash(timestamp, did),
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("result") is not True:
            raise RuntimeError(f"SK Cinemas API failed: {data.get('message')}")
        return data

    def _movie_map(self, payload: dict) -> dict[str, ScrapedMovie]:
        data = payload.get("data") or {}
        media_by_movie: dict[str, dict] = {}
        for section_name in ["newestMovie", "comingSoon"]:
            section = data.get(section_name) or {}
            for media in section.get("FilmUrl") or []:
                movie_id = media.get("FilmNameID")
                if not movie_id:
                    continue
                entry = media_by_movie.setdefault(movie_id, {"stills": []})
                if media.get("FU_Type") == 0 and media.get("FU_FileName"):
                    entry["poster_url"] = media.get("FU_FileName")
                elif media.get("FU_Type") == 1 and media.get("FU_FileName"):
                    entry["stills"].append(media.get("FU_FileName"))
                elif media.get("FU_Type") == 2 and media.get("FUL_youtubeURL"):
                    entry["trailer_url"] = media.get("FUL_youtubeURL")

        movies: dict[str, ScrapedMovie] = {}
        for section_name in ["newestMovie", "comingSoon"]:
            section = data.get(section_name) or {}
            for movie_payload in section.get("Film") or []:
                movie_id = movie_payload.get("FilmNameID")
                if not movie_id:
                    continue
                media = media_by_movie.get(movie_id, {})
                movies[movie_id] = ScrapedMovie(
                    title=movie_payload.get("FilmName")
                    or movie_payload.get("TitleAlt")
                    or f"Shin Kong Movie {movie_id}",
                    title_zh=movie_payload.get("FilmName"),
                    title_en=movie_payload.get("TitleAlt"),
                    original_title=movie_payload.get("TitleAlt"),
                    poster_url=media.get("poster_url"),
                    still_urls=media.get("stills") or None,
                    release_date=self._parse_date(movie_payload.get("_openDate")),
                    duration_minutes=self._parse_int(movie_payload.get("RunTime")),
                    rating=movie_payload.get("Rating"),
                    description=movie_payload.get("RatingDescription"),
                    trailer_url=media.get("trailer_url"),
                    detail_url=f"{SITE_BASE_URL}/films/{movie_id}",
                    source_movie_id=movie_id,
                )
        return movies

    def _format_info(self, film_type: str | None) -> dict[str, str | None]:
        label = self._clean_text(film_type) or "數位"
        upper = label.upper()

        language = None
        if "英語" in label or "英文" in label:
            language = "英語"
        elif "日語" in label or "日文" in label:
            language = "日語"
        elif "國語" in label or "中文" in label:
            language = "國語"

        auditorium_brand = None
        if "DOLBY" in upper:
            auditorium_brand = "Dolby Cinema"
        elif "MX4D" in upper:
            auditorium_brand = "MX4D"
        elif "LUXE" in upper:
            auditorium_brand = "LUXE"
        elif "B．O．X" in label or "B.O.X" in upper or "BOX" in upper:
            auditorium_brand = "B.O.X"

        projection_type = "3D" if "3D" in upper else "數位"
        return {
            "format": label,
            "language": language,
            "version_label": label,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
        }

    def _security_hash(
        self,
        timestamp: str,
        did: str,
        customer_id: str = "",
        mobile: str = "",
    ) -> str:
        secret = self._defs("guRt^V]B\tCEwD{uNyX@c_w?{@br>Q\x04[X", 13)
        integer_timestamp = int(timestamp)
        ingredient = secret
        if integer_timestamp % 3 == 0:
            ingredient = secret[7:] + secret[3:18]
        elif integer_timestamp % 3 == 1:
            ingredient = secret[4:12] + secret[5:]
        elif integer_timestamp % 3 == 2:
            ingredient = secret[3:] + secret[6:19]

        messages = [
            timestamp + mobile + ingredient + did + customer_id + secret + mobile,
            secret + customer_id + mobile + customer_id + ingredient + did + timestamp,
            did + mobile + ingredient + customer_id + timestamp + secret,
            customer_id + secret + mobile + ingredient + timestamp + did,
            mobile + timestamp + secret + timestamp + customer_id + did,
            did + ingredient + timestamp + mobile + customer_id + did,
        ]
        message = messages[integer_timestamp % 6]
        return hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest().upper()

    def _defs(self, value: str, offset: int, limit: int = 126) -> str:
        return "".join(
            chr((ord(char) + limit - offset) % limit)
            if ord(char) <= limit
            else char
            for char in value
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _parse_date(self, value: str | None):
        return self._parse_datetime(value).date() if self._parse_datetime(value) else None

    def _parse_int(self, value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()) or None

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
