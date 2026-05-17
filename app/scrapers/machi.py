from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://fmmfilmmate.tixi.com.tw"
CHAIN = "Machi Cinema"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="新莊鴻金寶麻吉影城",
    city="新北",
    address="新北市新莊區民安路188巷5號4樓",
    source_cinema_id="machi-xinzhuang",
)


class MachiCinemaScraper:
    """Scraper for Machi Cinema's TIXI showtime site."""

    def scrape(self) -> list[ScrapedShowtime]:
        first_page = self._fetch_page()
        dates = self._available_dates(first_page)
        pages = {self._selected_date(first_page): first_page}

        for show_date in dates:
            if show_date not in pages:
                pages[show_date] = self._fetch_page(show_date)

        results: list[ScrapedShowtime] = []
        for page in pages.values():
            results.extend(self._showtimes_from_page(page))

        results = self._dedupe(results)
        if not results:
            raise RuntimeError("machi scraper found no showtimes; keeping existing data")
        return results

    def _showtimes_from_page(self, soup: BeautifulSoup) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for card in soup.select("#selMovie .card"):
            movie = self._movie_from_card(card)
            for room, version_label, links in self._room_groups(card):
                format_info = self._parse_format(version_label)
                for link in links:
                    payload = self._showtime_payload(link)
                    if not payload:
                        continue
                    show_datetime, program_code, room_code = payload
                    source_showtime_id = (
                        f"machi:{program_code}:{room_code}:"
                        f"{show_datetime.strftime('%Y-%m-%dT%H:%M')}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_datetime.date(),
                            start_time=show_datetime.time(),
                            hall_name=room,
                            format=format_info["format"],
                            language=format_info["language"],
                            booking_url=SITE_BASE_URL,
                            source="machi",
                            source_showtime_id=source_showtime_id,
                            version_label=version_label,
                            projection_type=format_info["format"],
                            audio_language=format_info["language"],
                            subtitle_language=None,
                            source_payload={
                                "program_code": program_code,
                                "room_code": room_code,
                                "tixi_parameter": link.get("onclick"),
                            },
                        )
                    )
        return results

    def _movie_from_card(self, card) -> ScrapedMovie:
        title_zh = self._first_text(card, ".movie_title")
        title_en = self._first_text(card, ".movie_title_en")
        text = card.get_text(" ", strip=True)
        return ScrapedMovie(
            title=title_zh or title_en or "Machi Cinema Movie",
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=self._poster_url(card),
            release_date=self._release_date(text),
            duration_minutes=self._duration_minutes(text),
            rating=self._rating(card),
            detail_url=SITE_BASE_URL,
            source_movie_id=self._program_code(card) or self._movie_key(title_zh, title_en),
        )

    def _room_groups(self, card) -> list[tuple[str | None, str | None, list]]:
        groups = []
        for room_node in card.select(".movie_times .room"):
            links = []
            sibling = room_node.find_next_sibling()
            while sibling and "room" not in (sibling.get("class") or []):
                if sibling.name == "ul" and "btn_time" in (sibling.get("class") or []):
                    links.extend(sibling.select("a[onclick]"))
                sibling = sibling.find_next_sibling()

            room_text = self._clean_text(room_node.find(string=True, recursive=False))
            version_label = self._clean_text(room_node.get_text(" ", strip=True))
            groups.append((room_text or None, version_label or None, links))
        return groups

    def _showtime_payload(self, link) -> tuple[datetime, str, str] | None:
        onclick = link.get("onclick") or ""
        match = re.search(r"SetCorp\('([^']+)'\)", onclick)
        if not match:
            return None
        parts = match.group(1).split("_")
        if len(parts) != 3:
            return None
        show_datetime = datetime.strptime(parts[0], "%Y/%m/%d %H:%M:%S")
        return show_datetime, parts[1], parts[2]

    def _fetch_page(self, show_date: str | None = None) -> BeautifulSoup:
        data = None
        if show_date:
            data = urlencode(
                {
                    "ChangeDate": show_date,
                    "selectDate": show_date,
                    "SysCode": "SC009",
                    "CoCode": "0001",
                    "CoName": "鴻金寶麻吉影城",
                }
            ).encode()
        return BeautifulSoup(self._fetch_text(SITE_BASE_URL, data=data), "lxml")

    def _fetch_text(self, url: str, data: bytes | None = None) -> str:
        request = Request(
            url,
            data=data,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Content-Type": "application/x-www-form-urlencoded",
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
            return response.read().decode("utf-8", errors="ignore")

    def _available_dates(self, soup: BeautifulSoup) -> list[str]:
        return [
            option.get("value")
            for option in soup.select("#selectDate option[value]")
            if option.get("value")
        ]

    def _selected_date(self, soup: BeautifulSoup) -> str | None:
        selected = soup.select_one("#selectDate option[selected][value]")
        return selected.get("value") if selected else None

    def _parse_format(self, value: str | None) -> dict[str, str | None]:
        text = value or ""
        format_match = re.search(r"\(([^)]+)\)", text)
        language_match = re.search(r"-\s*([^\s]+)", text)
        return {
            "format": format_match.group(1) if format_match else "數位",
            "language": self._normalize_language(
                language_match.group(1) if language_match else None
            ),
        }

    def _normalize_language(self, value: str | None) -> str | None:
        if not value:
            return None
        if "國" in value or "中" in value:
            return "中文"
        if "英" in value:
            return "英文"
        if "日" in value:
            return "日文"
        if "粵" in value:
            return "粵語"
        if "台" in value:
            return "台語"
        if "韓" in value:
            return "韓語"
        return value

    def _release_date(self, text: str):
        match = re.search(r"上映日期：(\d{4})/(\d{1,2})/(\d{1,2})", text)
        if not match:
            return None
        return datetime.strptime(match.group(0).split("：", 1)[1], "%Y/%m/%d").date()

    def _duration_minutes(self, text: str) -> int | None:
        match = re.search(r"片長：(?:(\d+)時)?(?:(\d+)分)?", text)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        return hours * 60 + minutes or None

    def _rating(self, card) -> str | None:
        return self._first_text(card, ".movie_level")

    def _poster_url(self, card) -> str | None:
        image = card.select_one("img[src]")
        if not image:
            return None
        src = image.get("src") or ""
        if src.startswith("data:"):
            return None
        return src if src.startswith("http") else SITE_BASE_URL + src

    def _program_code(self, card) -> str | None:
        link = card.select_one("a[onclick]")
        payload = self._showtime_payload(link) if link else None
        return payload[1] if payload else None

    def _first_text(self, node, selector: str) -> str | None:
        match = node.select_one(selector)
        return self._clean_text(match.get_text(" ", strip=True)) if match else None

    def _movie_key(self, *values: str | None) -> str | None:
        key = re.sub(r"[\W_]+", "", "-".join(value or "" for value in values)).lower()
        return key or None

    def _clean_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip()

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
