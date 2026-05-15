from __future__ import annotations

import json
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

API_BASE_URL = "https://capi.showtimes.com.tw/4"
BOOTSTRAP_URL = f"{API_BASE_URL}/app/bootstrap"
SITE_BASE_URL = "https://www.showtimes.com.tw"
CHAIN = "Showtime Cinemas"
TIMEZONE = ZoneInfo("Asia/Taipei")


RATING_BY_CODE = {
    "g": "普遍級",
    "p": "保護級",
    "pg12": "輔12級",
    "pg15": "輔15級",
    "r": "限制級",
}

GENRE_BY_CODE = {
    "action": "動作",
    "adventure": "冒險",
    "animation": "動畫",
    "biography": "傳記",
    "comedy": "喜劇",
    "crime": "犯罪",
    "drama": "劇情",
    "fantasy": "奇幻",
    "history": "歷史",
    "horror": "恐怖",
    "music": "音樂/歌舞",
    "mystery": "推理",
    "romance": "愛情",
    "science fiction": "科幻",
    "thriller": "驚悚",
}


class ShowtimeCinemasScraper:
    """Scraper for Showtime Cinemas.

    Showtime exposes the public ticketing data through the same bootstrap API
    used by its web app. The payload contains cinemas, programs, venues, and
    active events grouped by corporation, so this scraper does not need browser
    rendering.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        payload = self._fetch_bootstrap_payload()
        return self._parse_bootstrap_payload(payload)

    def _fetch_bootstrap_payload(self) -> dict:
        request = Request(
            BOOTSTRAP_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": SITE_BASE_URL,
            },
        )
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("payload", data)

    def _parse_bootstrap_payload(self, payload: dict) -> list[ScrapedShowtime]:
        corporations = {
            int(corporation["id"]): corporation
            for corporation in payload.get("corporations", [])
            if corporation.get("id") is not None
        }
        programs = {
            int(program["id"]): program
            for program in payload.get("programs", [])
            if program.get("id") is not None
        }

        results: list[ScrapedShowtime] = []
        events_for_corporations = payload.get("eventsForCorporations", {})
        for corporation_id_text, group in events_for_corporations.items():
            try:
                corporation_id = int(corporation_id_text)
            except (TypeError, ValueError):
                continue
            corporation = corporations.get(corporation_id)
            if not corporation:
                continue

            venues = {
                int(venue["id"]): venue
                for venue in group.get("venues", [])
                if venue.get("id") is not None
            }
            cinema = self._cinema_from_corporation(corporation)

            for event in group.get("events", []):
                if event.get("status") != "active":
                    continue
                program = programs.get(event.get("programId"))
                if not program:
                    continue
                started_at = self._parse_datetime(event.get("startedAt"))
                if not started_at:
                    continue

                format_info = self._parse_format(event.get("meta", {}).get("format"))
                movie = self._movie_from_program(program)
                venue = venues.get(event.get("venueId"))
                showtime = ScrapedShowtime(
                    cinema=cinema,
                    movie=movie,
                    show_date=started_at.date(),
                    start_time=started_at.time().replace(second=0, microsecond=0),
                    hall_name=venue.get("room") if venue else None,
                    format=format_info["format"],
                    language=format_info["language"],
                    booking_url=f"{SITE_BASE_URL}/ticketing/cart/selectTicketTypes/{event['id']}",
                    source="showtimes",
                    source_showtime_id=f"showtimes:{event['id']}",
                    version_label=format_info["version_label"],
                    auditorium_brand=format_info["auditorium_brand"],
                    projection_type=format_info["projection_type"],
                    audio_language=format_info["language"],
                    subtitle_language=None,
                    source_payload={
                        "event": event,
                        "venue": venue,
                        "corporation": {
                            "id": corporation.get("id"),
                            "name": corporation.get("name"),
                        },
                    },
                )
                results.append(showtime)

        return results

    def _cinema_from_corporation(self, corporation: dict) -> ScrapedCinema:
        address = corporation.get("address")
        return ScrapedCinema(
            chain=CHAIN,
            name=corporation.get("name") or f"Showtime Cinemas {corporation.get('id')}",
            city=self._city_from_address(address),
            address=address,
            source_cinema_id=str(corporation.get("id")) if corporation.get("id") is not None else None,
        )

    def _movie_from_program(self, program: dict) -> ScrapedMovie:
        meta = program.get("meta") or {}
        cover = program.get("coverImagePortrait") or {}
        preview = program.get("previewVideo") or {}
        return ScrapedMovie(
            title=program.get("name") or f"Showtime Program {program.get('id')}",
            title_zh=program.get("name"),
            title_en=program.get("nameAlternative"),
            original_title=program.get("nameAlternative"),
            poster_url=cover.get("url"),
            release_date=self._parse_date(program.get("availableAt")),
            duration_minutes=self._duration_minutes(program.get("duration")),
            rating=RATING_BY_CODE.get(program.get("rating") or ""),
            genre=self._genre_text(program.get("genres") or []),
            description=program.get("description"),
            director="、".join(meta.get("directors") or []) or None,
            cast="、".join(meta.get("authors") or []) or None,
            trailer_url=preview.get("url"),
            detail_url=f"{SITE_BASE_URL}/programs/{program['id']}" if program.get("id") else None,
            source_movie_id=str(program.get("id")) if program.get("id") is not None else None,
        )

    def _parse_format(self, raw_format: str | None) -> dict[str, str | None]:
        text = (raw_format or "").strip()
        parts = text.split()
        language = None
        if parts and self._language_from_token(parts[-1]):
            language = self._language_from_token(parts[-1])
            format_text = " ".join(parts[:-1]).strip()
        else:
            format_text = text

        short_language = self._short_language(language)
        version_label = f"{format_text}({short_language})" if format_text and short_language else text or None
        upper_format = format_text.upper()
        auditorium_brand = None
        for brand in [
            "ULTRA 4DX",
            "SCREENX",
            "DVA",
            "ATMOS",
            "REMMI",
            "4DX",
            "TEMPUR",
            "丹普",
            "巨幕",
        ]:
            if brand in upper_format or brand in format_text:
                auditorium_brand = brand
                break

        projection_type = None
        if "3D" in upper_format:
            projection_type = "3D"
        elif "2D" in upper_format or "數位" in format_text:
            projection_type = "數位"

        return {
            "format": format_text or None,
            "language": language,
            "version_label": version_label,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
        }

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(TIMEZONE)

    def _parse_date(self, value: str | None):
        parsed = self._parse_datetime(value)
        return parsed.date() if parsed else None

    def _duration_minutes(self, duration_seconds: int | None) -> int | None:
        if not duration_seconds:
            return None
        return int(round(duration_seconds / 60))

    def _genre_text(self, genres: list[str]) -> str | None:
        names = [GENRE_BY_CODE.get(genre, genre) for genre in genres]
        return "、".join(names) if names else None

    def _language_from_token(self, token: str) -> str | None:
        mapping = {
            "國語": "國語",
            "中文": "國語",
            "英語": "英語",
            "日語": "日語",
            "韓語": "韓語",
            "粵語": "粵語",
            "多元語": "多元語",
        }
        return mapping.get(token)

    def _short_language(self, language: str | None) -> str | None:
        mapping = {
            "國語": "國",
            "英語": "英",
            "日語": "日",
            "韓語": "韓",
            "粵語": "粵",
            "多元語": "多元語",
        }
        return mapping.get(language or "")

    def _city_from_address(self, address: str | None) -> str | None:
        if not address:
            return None
        city_aliases = {
            "台北市": "台北",
            "臺北市": "台北",
            "新北市": "新北",
            "桃園市": "桃園",
            "新竹市": "新竹",
            "苗栗縣": "苗栗",
            "台中市": "台中",
            "臺中市": "台中",
            "台南市": "台南",
            "臺南市": "台南",
            "高雄市": "高雄",
            "基隆市": "基隆",
            "嘉義市": "嘉義",
            "嘉義縣": "嘉義",
            "雲林縣": "雲林",
            "台東市": "台東",
            "臺東市": "台東",
            "台東縣": "台東",
            "臺東縣": "台東",
            "花蓮市": "花蓮",
            "花蓮縣": "花蓮",
        }
        for prefix, city in city_aliases.items():
            if prefix in address:
                return city
        return None
