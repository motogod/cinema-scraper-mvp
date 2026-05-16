from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from urllib.request import Request, urlopen

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.broadway-cineplex.com.tw"
CHAIN = "Broadway Cinemas"

CINEMAS = {
    "Taipei": ScrapedCinema(
        chain=CHAIN,
        name="百老匯公館店",
        city="台北",
        address="台北市文山區羅斯福路四段200號",
        source_cinema_id="Taipei",
    ),
    "Zhubei": ScrapedCinema(
        chain=CHAIN,
        name="百老匯竹北店",
        city="新竹",
        address="新竹縣竹北市自強南路36號3~5樓",
        source_cinema_id="Zhubei",
    ),
}


class BroadwayScraper:
    """Scraper for Broadway Cinemas' public movie/showtime JSON endpoints."""

    def scrape(self) -> list[ScrapedShowtime]:
        cinemas = self._fetch_cinema_ids()
        results: list[ScrapedShowtime] = []
        for cinema_id in cinemas:
            movies = self._fetch_movie_list(cinema_id)
            for movie_payload in movies:
                movie = self._movie_from_payload(movie_payload)
                results.extend(self._showtimes_for_movie(cinema_id, movie, movie_payload))
        return self._dedupe(results)

    def _showtimes_for_movie(
        self,
        cinema_id: str,
        movie: ScrapedMovie,
        movie_payload: dict,
    ) -> list[ScrapedShowtime]:
        cinema = CINEMAS.get(cinema_id) or ScrapedCinema(
            chain=CHAIN,
            name=f"百老匯影城 {cinema_id}",
            source_cinema_id=cinema_id,
        )
        program_id = movie.source_movie_id
        if not program_id:
            return []

        initial_by_date = self._timedata_by_date(movie_payload.get("timedata") or [])
        dates = self._available_dates(movie_payload)
        results: list[ScrapedShowtime] = []
        for show_date in dates:
            timedata = initial_by_date.get(show_date.isoformat())
            if timedata is None:
                timedata = self._fetch_movie_times(cinema_id, program_id, show_date)
            results.extend(self._parse_timedata(cinema, movie, show_date, timedata))
        return results

    def _parse_timedata(
        self,
        cinema: ScrapedCinema,
        movie: ScrapedMovie,
        fallback_date: date,
        timedata: list[dict],
    ) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for format_group in timedata:
            group_format = self._clean_text(format_group.get("SubName2"))
            for item in format_group.get("subtimedata") or []:
                start_time = self._parse_time(item.get("時間"))
                if not start_time:
                    continue
                show_date = self._parse_date(item.get("showdate")) or fallback_date
                raw_format = self._clean_text(item.get("SubName2")) or group_format
                format_info = self._parse_format(raw_format, item.get("SubCode"))
                hall_id = self._clean_text(item.get("hall"))
                source_showtime_id = (
                    f"broadway:{cinema.source_cinema_id}:{movie.source_movie_id}:"
                    f"{show_date.isoformat()}:{start_time.strftime('%H:%M')}:{hall_id or ''}:"
                    f"{item.get('SubCode') or ''}"
                )
                results.append(
                    ScrapedShowtime(
                        cinema=cinema,
                        movie=movie,
                        show_date=show_date,
                        start_time=start_time,
                        hall_name=self._clean_text(item.get("hallname")) or hall_id,
                        format=format_info["format"],
                        language=format_info["language"],
                        booking_url=self._booking_url(cinema.source_cinema_id, movie.source_movie_id),
                        source="broadway",
                        source_showtime_id=source_showtime_id,
                        version_label=raw_format,
                        auditorium_brand=format_info["auditorium_brand"],
                        projection_type=format_info["projection_type"],
                        audio_language=format_info["language"],
                        subtitle_language=format_info["subtitle_language"],
                        source_payload={
                            "showtime": item,
                            "format_group": {"SubName2": group_format},
                        },
                    )
                )
        return results

    def _movie_from_payload(self, payload: dict) -> ScrapedMovie:
        title_zh = self._clean_text(payload.get("cname"))
        title_en = self._clean_text(payload.get("ename"))
        title = title_zh or title_en or f"Broadway Program {payload.get('programid')}"
        return ScrapedMovie(
            title=title,
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=self._clean_text(payload.get("image") or payload.get("img")),
            release_date=self._parse_date(payload.get("ReleaseDate")),
            duration_minutes=self._parse_int(payload.get("ShowTimes")),
            rating=self._rating(payload.get("CodeName"), payload.get("filmlevel")),
            genre=self._genre(payload.get("CodeName")),
            description=self._clean_text(payload.get("Introduction")),
            director=self._clean_text(payload.get("Director")),
            cast=self._clean_text(payload.get("Actors")),
            trailer_url=self._clean_text(payload.get("YTurl")),
            detail_url=f"{SITE_BASE_URL}/movie-info.html?obj={payload.get('programid')}",
            source_movie_id=str(payload.get("programid")) if payload.get("programid") else None,
        )

    def _fetch_cinema_ids(self) -> list[str]:
        payload = self._request_json(f"{SITE_BASE_URL}/Movie/GetTheater")
        ids = [
            item.get("item_value")
            for item in payload.get("Data", [])
            if item.get("item_value") and item.get("item_value") in CINEMAS
        ]
        return ids or list(CINEMAS)

    def _fetch_movie_list(self, cinema_id: str) -> list[dict]:
        payload = self._request_json(f"{SITE_BASE_URL}/Movie/GetMovieList/{cinema_id}")
        if not payload.get("status"):
            return []
        return payload.get("Data") or []

    def _fetch_movie_times(self, cinema_id: str, program_id: str, show_date: date) -> list[dict]:
        url = (
            f"{SITE_BASE_URL}/Movie/GetMovieAlltime/"
            f"{cinema_id}/{program_id}/{show_date.isoformat()}"
        )
        payload = self._request_json(url)
        if not payload.get("status"):
            return []
        return payload.get("Data") or []

    def _request_json(self, url: str) -> dict:
        request = Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
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
            return json.loads(response.read().decode("utf-8-sig"))

    def _available_dates(self, payload: dict) -> list[date]:
        dates: list[date] = []
        for item in payload.get("datedata") or []:
            parsed = self._parse_date(item.get("date"))
            if parsed:
                dates.append(parsed)
        return dates

    def _timedata_by_date(self, timedata: list[dict]) -> dict[str, list[dict]]:
        by_date: dict[str, list[dict]] = {}
        for group in timedata:
            dates = {
                item.get("showdate")
                for item in group.get("subtimedata") or []
                if item.get("showdate")
            }
            for show_date in dates:
                by_date.setdefault(show_date, []).append(group)
        return by_date

    def _parse_format(self, raw_format: str | None, sub_code: str | None) -> dict[str, str | None]:
        text = raw_format or ""
        parts = [part.strip() for part in text.split("/") if part.strip()]
        format_text = parts[0] if parts else None
        language = self._language(parts[1] if len(parts) > 1 else text)
        upper_code = (sub_code or "").upper()

        auditorium_brand = None
        if format_text in {"VIP", "巨幕"}:
            auditorium_brand = format_text
        elif "VIP" in upper_code:
            auditorium_brand = "VIP"
        elif "GSC" in upper_code:
            auditorium_brand = "巨幕"

        projection_type = None
        upper_text = text.upper()
        if "3D" in upper_text or "3D" in upper_code:
            projection_type = "3D"
        elif format_text:
            projection_type = "數位"

        return {
            "format": format_text,
            "language": language,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
            "subtitle_language": "中文字幕" if upper_code.endswith("CHT") else None,
        }

    def _language(self, value: str | None) -> str | None:
        text = value or ""
        mapping = {
            "英文": "英語",
            "英語": "英語",
            "日文": "日語",
            "日語": "日語",
            "韓文": "韓語",
            "韓語": "韓語",
            "中文": "國語",
            "國語": "國語",
            "粵語": "粵語",
            "泰語": "泰語",
        }
        for key, language in mapping.items():
            if key in text:
                return language
        return None

    def _rating(self, code_name: str | None, filmlevel: str | None) -> str | None:
        text = f"{code_name or ''} {filmlevel or ''}"
        mapping = {
            "yn": "普遍級",
            "普通": "普遍級",
            "yp": "保護級",
            "保護": "保護級",
            "y12": "輔12級",
            "輔導十二": "輔12級",
            "y15": "輔15級",
            "輔導十五": "輔15級",
            "R": "限制級",
            "限制": "限制級",
        }
        for key, rating in mapping.items():
            if key in text:
                return rating
        return self._clean_text(code_name)

    def _genre(self, code_name: str | None) -> str | None:
        rating_words = ("普通", "保護", "輔導", "限制", "未定")
        text = self._clean_text(code_name)
        if not text or any(word in text for word in rating_words):
            return None
        return text

    def _booking_url(self, cinema_id: str | None, program_id: str | None) -> str:
        if cinema_id and program_id:
            return f"{SITE_BASE_URL}/book.html?obj={cinema_id}&pid={program_id}"
        return f"{SITE_BASE_URL}/book.html"

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _parse_time(self, value: str | None) -> time | None:
        match = re.search(r"\d{1,2}:\d{2}", value or "")
        return datetime.strptime(match.group(0), "%H:%M").time() if match else None

    def _parse_int(self, value: str | int | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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
