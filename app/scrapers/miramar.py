from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.request import Request, urlopen

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.miramarcinemas.tw"
API_URL = f"{SITE_BASE_URL}/api/Booking/GetMovie/"
CHAIN = "Miramar Cinemas"

CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="美麗華影城",
    city="台北",
    address="台北市中山區敬業三路22號6樓",
    source_cinema_id="miramar-da-zhi",
)


class MiramarScraper:
    """Scraper for Miramar Cinemas.

    Miramar's booking widget fetches movie and session data from
    `/api/Booking/GetMovie/`. The payload already contains the movie metadata
    and showtimes grouped by date and cinema/session type.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        payload = self._fetch_payload()
        movies = payload.get("results", {}).get("mMovies", [])
        results: list[ScrapedShowtime] = []
        for movie_payload in movies:
            movie = self._movie_from_payload(movie_payload)
            for show_date_payload in movie_payload.get("mShowTimes") or []:
                for cinema_payload in show_date_payload.get("mCinemas") or []:
                    format_info = self._format_info(
                        cinema_payload.get("CinemaTitle"),
                        movie_payload.get("ArrRoomTitle"),
                    )
                    for session in cinema_payload.get("mSessions") or []:
                        show_at = self._parse_datetime(session.get("Showtime"))
                        if not show_at:
                            continue
                        session_id = str(session.get("SessionId") or "")
                        source_key = (
                            f"miramar:{movie_payload.get('ID')}:{session_id}:"
                            f"{show_at.isoformat()}:{format_info['version_label'] or ''}"
                        )
                        results.append(
                            ScrapedShowtime(
                                cinema=CINEMA,
                                movie=movie,
                                show_date=show_at.date(),
                                start_time=show_at.time().replace(second=0, microsecond=0),
                                hall_name=session.get("ScreenName"),
                                format=format_info["format"],
                                language=format_info["language"],
                                booking_url=self._booking_url(movie_payload.get("ID"), session_id),
                                source="miramar",
                                source_showtime_id=source_key,
                                version_label=format_info["version_label"],
                                auditorium_brand=format_info["auditorium_brand"],
                                projection_type=format_info["projection_type"],
                                audio_language=format_info["language"],
                                subtitle_language=None,
                                source_payload={
                                    "movie_id": movie_payload.get("ID"),
                                    "session": session,
                                    "cinema": cinema_payload,
                                },
                            )
                        )
        return self._dedupe(results)

    def _fetch_payload(self) -> dict:
        request = Request(
            API_URL,
            data=json.dumps({"AccessToken": ""}).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/json; charset=utf-8",
                "Referer": SITE_BASE_URL,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def _movie_from_payload(self, payload: dict) -> ScrapedMovie:
        return ScrapedMovie(
            title=payload.get("TitleAlt") or payload.get("Title") or f"Miramar Movie {payload.get('ID')}",
            title_zh=payload.get("TitleAlt"),
            title_en=payload.get("Title"),
            original_title=payload.get("Title"),
            poster_url=payload.get("GraphicUrl"),
            still_urls=payload.get("Stills") or None,
            release_date=self._parse_date(payload.get("OpeningDate")),
            duration_minutes=self._parse_int(payload.get("RunTime")),
            rating=payload.get("Rating"),
            genre=payload.get("Gener"),
            description=payload.get("Synopsis") or payload.get("ShortSynopsis"),
            director=payload.get("Director"),
            cast=payload.get("Cast"),
            trailer_url=payload.get("TrailerUrl") or None,
            detail_url=f"{SITE_BASE_URL}/Movie/Detail?id={payload.get('ID')}&type=now"
            if payload.get("ID")
            else None,
            source_movie_id=payload.get("ID"),
        )

    def _format_info(
        self,
        cinema_title: str | None,
        room_title: str | None,
    ) -> dict[str, str | None]:
        title = self._clean_text(cinema_title) or ""
        language = self._language(title)

        auditorium_brand = None
        upper_title = title.upper()
        if "DOLBY" in upper_title:
            auditorium_brand = "Dolby Cinema"
        elif "IMAX" in upper_title:
            auditorium_brand = "IMAX"
        elif "HFR" in upper_title:
            auditorium_brand = "HFR"

        projection_type = None
        if "3D" in upper_title:
            projection_type = "3D"
        elif title and ("標準" in title or "IMAX" in upper_title or "DOLBY" in upper_title):
            projection_type = "數位"

        format_label = title
        for token in ["中文(CHI)", "英文(ENG)", "日文(JPN)", "韓文(KOR)"]:
            format_label = format_label.replace(token, "").strip()
        if not format_label and auditorium_brand:
            format_label = auditorium_brand

        version_parts = []
        if auditorium_brand and auditorium_brand not in (format_label or ""):
            version_parts.append(auditorium_brand)
        if format_label:
            version_parts.append(format_label)
        if language:
            version_parts.append(language)

        return {
            "format": format_label or None,
            "language": language,
            "version_label": "‧".join(dict.fromkeys(version_parts)) or None,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
        }

    def _booking_url(self, movie_id: str | None, session_id: str | None) -> str | None:
        if not movie_id or not session_id:
            return SITE_BASE_URL
        return f"{SITE_BASE_URL}/Booking/TicketType?id={movie_id}&session={session_id}"

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None

    def _parse_int(self, value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _language(self, value: str | None) -> str | None:
        text = value or ""
        if "英文" in text or "ENG" in text.upper():
            return "英語"
        if "中文" in text or "CHI" in text.upper() or "國語" in text:
            return "國語"
        if "日文" in text or "JPN" in text.upper() or "日語" in text:
            return "日語"
        if "韓文" in text or "KOR" in text.upper() or "韓語" in text:
            return "韓語"
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
