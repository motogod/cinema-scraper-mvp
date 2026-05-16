from __future__ import annotations

import re
from datetime import date, datetime, time
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://breezecinemas.tixi.com.tw/"
CHAIN = "Breeze Cinemas"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="微風影城",
    city="台北",
    address="台北市松山區復興南路一段39號8樓",
    source_cinema_id="0001",
)
SYS_CODE = "SC008"
CO_CODE = "0001"
CO_NAME = "微風影城"


class BreezeCinemasScraper:
    """Scraper for Breeze Cinemas' Tixi showtime site."""

    def __init__(self) -> None:
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def scrape(self) -> list[ScrapedShowtime]:
        initial_html = self._fetch_initial_html()
        dates = self._available_dates(BeautifulSoup(initial_html, "lxml"))
        results: list[ScrapedShowtime] = []
        for show_date in dates:
            html = self._post_date(show_date)
            results.extend(self._parse_showtimes(html, show_date))
        return self._dedupe(results)

    def _parse_showtimes(self, html: str, fallback_date: date) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(html, "lxml")
        results: list[ScrapedShowtime] = []
        for card in soup.select("#selMovie .card"):
            movie = self._movie_from_card(card)
            for room_node in card.select(".movie_times .room"):
                hall_name, showtime_format = self._room_info(room_node)
                time_list = room_node.find_next_sibling("ul", class_="btn_time")
                if not time_list:
                    continue
                for anchor in time_list.select("a[onclick]"):
                    session = self._session_from_onclick(anchor.get("onclick"))
                    start_at = session.get("start_at")
                    start_time = start_at.time().replace(second=0, microsecond=0) if start_at else self._parse_time(anchor.get_text(" ", strip=True))
                    if not start_time:
                        continue
                    show_date = start_at.date() if start_at else fallback_date
                    source_movie_id = session.get("program_code") or movie.source_movie_id
                    if source_movie_id and source_movie_id != movie.source_movie_id:
                        movie = ScrapedMovie(**{**movie.__dict__, "source_movie_id": source_movie_id})
                    source_key = (
                        f"breezecinemas:{show_date.isoformat()}:"
                        f"{start_time.strftime('%H:%M')}:{source_movie_id or ''}:"
                        f"{session.get('venue_room_code') or hall_name or ''}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=hall_name,
                            format=showtime_format,
                            language=self._language(showtime_format),
                            booking_url=SITE_BASE_URL,
                            source="breezecinemas",
                            source_showtime_id=source_key,
                            version_label=showtime_format,
                            auditorium_brand=None,
                            projection_type=self._projection_type(showtime_format),
                            audio_language=self._language(showtime_format),
                            subtitle_language=None,
                            source_payload={
                                "session": self._serializable_session(session),
                                "room_text": self._clean_text(room_node.get_text(" ", strip=True)),
                            },
                        )
                    )
        return results

    def _movie_from_card(self, card) -> ScrapedMovie:
        title_zh = self._first_text(card, ".movie_title")
        title_en = self._first_text(card, ".movie_title_en")
        meta = self._movie_meta(card)
        title = title_zh or title_en or "微風影城電影"
        poster_url = self._poster_url(card)
        source_movie_id = self._first_program_code(card)
        return ScrapedMovie(
            title=title,
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=poster_url,
            release_date=self._parse_date(meta.get("上映日期")),
            duration_minutes=self._parse_duration(meta.get("片長")),
            rating=self._rating(meta.get("級數")),
            detail_url=SITE_BASE_URL,
            source_movie_id=source_movie_id,
        )

    def _movie_meta(self, card) -> dict[str, str]:
        meta: dict[str, str] = {}
        for item in card.select(".movie_data li"):
            text = self._clean_text(item.get_text(" ", strip=True))
            if not text:
                continue
            match = re.search(r"(上映日期|片長|級數)：\s*(?P<value>.+)", text)
            if match:
                meta[match.group(1)] = match.group("value").strip()
        return meta

    def _room_info(self, room_node) -> tuple[str | None, str | None]:
        text = self._clean_text(room_node.get_text(" ", strip=True))
        if not text:
            return None, None
        hall_name = text.split(" ", 1)[0].replace("\xa0", "").strip() or None
        format_match = re.search(r"\((?P<format>[^)]+)\)", text)
        showtime_format = format_match.group("format") if format_match else "數位"
        return hall_name, showtime_format

    def _session_from_onclick(self, value: str | None) -> dict[str, str | datetime | None]:
        match = re.search(r"SetCorp\('(?P<payload>[^']+)'\)", value or "")
        if not match:
            return {"start_at": None, "program_code": None, "venue_room_code": None}
        parts = match.group("payload").split("_")
        return {
            "start_at": self._parse_datetime(parts[0] if len(parts) > 0 else None),
            "program_code": parts[1] if len(parts) > 1 else None,
            "venue_room_code": parts[2] if len(parts) > 2 else None,
        }

    def _serializable_session(self, session: dict[str, str | datetime | None]) -> dict[str, str | None]:
        return {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in session.items()
        }

    def _first_program_code(self, card) -> str | None:
        for anchor in card.select("a[onclick]"):
            session = self._session_from_onclick(anchor.get("onclick"))
            program_code = session.get("program_code")
            if isinstance(program_code, str) and program_code:
                return program_code
        return None

    def _available_dates(self, soup: BeautifulSoup) -> list[date]:
        dates: list[date] = []
        for option in soup.select("#selectDate option[value]"):
            parsed = self._parse_date(option.get("value"))
            if parsed:
                dates.append(parsed)
        return dates

    def _post_date(self, show_date: date) -> str:
        html = self._fetch_initial_html()
        token = self._request_token(BeautifulSoup(html, "lxml"))
        payload = urlencode(
            {
                "__RequestVerificationToken": token or "",
                "selectDate": show_date.isoformat(),
                "ChangeDate": show_date.isoformat(),
                "SysCode": SYS_CODE,
                "CoCode": CO_CODE,
                "CoName": CO_NAME,
            }
        ).encode("utf-8")
        return self._request(SITE_BASE_URL, data=payload)

    def _fetch_initial_html(self) -> str:
        return self._request(SITE_BASE_URL)

    def _request(self, url: str, data: bytes | None = None) -> str:
        request = Request(
            url,
            data=data,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            method="POST" if data else "GET",
        )
        with self._opener.open(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _request_token(self, soup: BeautifulSoup) -> str | None:
        token = soup.select_one('form#formShowTime input[name="__RequestVerificationToken"]')
        return token.get("value") if token else None

    def _poster_url(self, card) -> str | None:
        image = card.select_one(".movie_info img[src]")
        if not image:
            return None
        src = image.get("src") or ""
        return None if src.startswith("data:") else src

    def _language(self, value: str | None) -> str | None:
        text = value or ""
        if "英" in text:
            return "英語"
        if "日" in text:
            return "日語"
        if "國" in text or "中" in text:
            return "國語"
        return None

    def _projection_type(self, value: str | None) -> str | None:
        text = (value or "").upper()
        if "3D" in text:
            return "3D"
        if value:
            return "數位"
        return None

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = self._clean_text(re.sub(r"\([^)]*\)", "", value)) or ""
        mapping = {
            "普遍級": "普遍級",
            "保護級": "保護級",
            "輔導12": "輔12級",
            "輔導15": "輔15級",
            "輔導級": "輔導級",
            "輔12級": "輔12級",
            "輔15級": "輔15級",
            "限制級": "限制級",
        }
        for key, rating in mapping.items():
            if key in text:
                return rating
        return text or None

    def _parse_duration(self, value: str | None) -> int | None:
        if not value:
            return None
        hour_match = re.search(r"(?P<hours>\d+)\s*時", value)
        minute_match = re.search(r"(?P<minutes>\d+)\s*分", value)
        hours = int(hour_match.group("hours")) if hour_match else 0
        minutes = int(minute_match.group("minutes")) if minute_match else 0
        total = hours * 60 + minutes
        return total or None

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            return None

    def _parse_time(self, value: str | None) -> time | None:
        match = re.search(r"\d{1,2}:\d{2}", value or "")
        return datetime.strptime(match.group(0), "%H:%M").time() if match else None

    def _first_text(self, node, selector: str) -> str | None:
        found = node.select_one(selector)
        return self._clean_text(found.get_text(" ", strip=True)) if found else None

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
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
