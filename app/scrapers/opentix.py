from __future__ import annotations

import json
import re
from hashlib import sha1
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SEARCH_URL = "https://search.opentix.life/search"
SITE_BASE_URL = "https://www.opentix.life"
SOURCE = "opentix"
CHAIN = "OpenTIX"
MOVIE_CATEGORIES = [
    "電影-劇情片",
    "電影-紀錄片",
    "電影-動畫",
    "電影-演出紀實",
]
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


class OpenTixScraper:
    """Scraper for OpenTIX movie programs and their venue showtimes."""

    def scrape(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        offset: int | None = 0
        seen_offsets: set[int] = set()

        while offset is not None and offset not in seen_offsets:
            seen_offsets.add(offset)
            payload = self._search(offset)
            result = payload.get("result") or {}
            for item in result.get("found") or []:
                source = item.get("source") or {}
                results.extend(self._showtimes_from_program(source))
            offset = result.get("nextOffset")

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("opentix scraper found no showtimes; keeping existing data")
        return results

    def _showtimes_from_program(self, program: dict) -> list[ScrapedShowtime]:
        program_id = str(program.get("id") or "").strip()
        if not program_id:
            return []

        movie = self._movie_from_program(program)
        results: list[ScrapedShowtime] = []
        for venue in program.get("eventVenues") or []:
            cinema = self._cinema_from_venue(venue)
            for time_item in venue.get("times") or []:
                starts_at = self._datetime_from_ms(time_item.get("start"))
                if starts_at is None:
                    continue
                venue_key = self._venue_key(venue)
                source_showtime_id = (
                    f"{SOURCE}:{program_id}:{venue_key}:"
                    f"{starts_at.strftime('%Y-%m-%dT%H:%M')}"
                )
                results.append(
                    ScrapedShowtime(
                        cinema=cinema,
                        movie=movie,
                        show_date=starts_at.date(),
                        start_time=starts_at.time(),
                        hall_name=venue.get("name"),
                        format=self._format(program.get("description")),
                        language=self._audio_language(program.get("description")),
                        booking_url=f"{SITE_BASE_URL}/event/{program_id}",
                        source=SOURCE,
                        source_showtime_id=source_showtime_id,
                        version_label=self._version_label(program, time_item),
                        projection_type=self._format(program.get("description")),
                        audio_language=self._audio_language(program.get("description")),
                        subtitle_language=self._subtitle_language(program.get("description")),
                        source_payload={
                            "program_id": program_id,
                            "venue": venue,
                            "time": time_item,
                        },
                    )
                )
        return results

    def _movie_from_program(self, program: dict) -> ScrapedMovie:
        title = self._clean_text(program.get("title")) or "OpenTIX Movie"
        english_title = self._clean_text(program.get("englishTitle"))
        description = self._clean_text(program.get("description"))
        return ScrapedMovie(
            title=title,
            title_zh=title,
            title_en=english_title,
            original_title=english_title,
            poster_url=self._clean_text(program.get("imageUrl")),
            duration_minutes=self._duration_minutes(description),
            rating=self._rating(program),
            genre=", ".join(program.get("categories") or []) or None,
            description=description,
            detail_url=f"{SITE_BASE_URL}/event/{program.get('id')}",
            source_movie_id=str(program.get("id") or ""),
        )

    def _cinema_from_venue(self, venue: dict) -> ScrapedCinema:
        city = self._clean_text(venue.get("city"))
        name = self._clean_text(venue.get("name")) or "OpenTIX Venue"
        return ScrapedCinema(
            chain=CHAIN,
            name=name,
            city=city,
            address=None,
            source_cinema_id=f"{SOURCE}:{self._venue_key(venue)}",
        )

    def _search(self, offset: int) -> dict:
        payload = {
            "language": "zh-CHT",
            "categoryFilter": MOVIE_CATEGORIES,
            "sortBy": "ABOUT_TO_BEGIN",
            "offset": offset,
        }
        data = json.dumps(payload).encode()
        request = Request(
            SEARCH_URL,
            data=data,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/json",
                "Origin": SITE_BASE_URL,
                "Referer": SITE_BASE_URL + "/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        )
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="ignore")
        parsed = json.loads(body)
        if parsed.get("error"):
            raise RuntimeError(f"opentix search failed: {parsed['error']}")
        return parsed

    def _datetime_from_ms(self, value) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=TAIPEI_TZ)
        except (TypeError, ValueError, OSError):
            return None

    def _duration_minutes(self, text: str | None) -> int | None:
        if not text:
            return None
        match = re.search(r"片長[：:]\s*(\d+)\s*分鐘", text)
        if not match:
            match = re.search(r"(\d+)\s*min", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _rating(self, program: dict) -> str | None:
        advise = self._clean_text(program.get("advise"))
        if advise and "請見" not in advise:
            return advise
        description = self._clean_text(program.get("description")) or ""
        match = re.search(r"(普遍級|保護級|輔(?:導)?\s*\d{1,2}級|限制級)", description)
        return match.group(1).replace(" ", "") if match else None

    def _format(self, text: str | None) -> str | None:
        match = re.search(r"放映規格[：:]\s*([^\s｜|，,。]+)", text or "")
        return match.group(1) if match else None

    def _audio_language(self, text: str | None) -> str | None:
        match = re.search(r"發音[：:]\s*([^\s字幕▲｜|，,。]+)", text or "")
        return self._clean_text(match.group(1)) if match else None

    def _subtitle_language(self, text: str | None) -> str | None:
        match = re.search(r"字幕[：:]\s*([^\s▲｜|，,。]+)", text or "")
        return self._clean_text(match.group(1)) if match else None

    def _venue_key(self, venue: dict) -> str:
        raw = f"{venue.get('city') or ''}:{venue.get('name') or ''}"
        return sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _version_label(self, program: dict, time_item: dict) -> str | None:
        price = self._price_label(time_item)
        categories = ", ".join(program.get("categories") or [])
        labels = [value for value in [categories, price] if value]
        return " / ".join(labels) or None

    def _price_label(self, time_item: dict) -> str | None:
        min_price = time_item.get("minPrice")
        max_price = time_item.get("maxPrice")
        if min_price is None or max_price is None:
            return None
        if min_price == max_price:
            return "免費" if min_price == 0 else f"${min_price}"
        return f"${min_price} - ${max_price}"

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output

    def _clean_text(self, value) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None
