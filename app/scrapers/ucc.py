from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "http://www.ucc-cinema.com.tw"
SCHEDULE_URL = f"{SITE_BASE_URL}/main03.asp"
CHAIN = "UCC Cinema"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="全球影城",
    city="台中",
    address="台中市西區中華路一段1-1號4樓",
    source_cinema_id="ucc-global",
)


class UccScraper:
    """Scraper for 全球影城/UCC.

    The old ASP page is Big5 encoded and renders showtimes as nested tables.
    Each schedule block contains one or more movies; showtime cells align with
    the title cells above them.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(self._fetch_text(SCHEDULE_URL), "lxml")
        results: list[ScrapedShowtime] = []
        for block_index, table in enumerate(self._schedule_tables(soup), start=1):
            results.extend(self._parse_schedule_table(table, block_index))
        return self._dedupe(results)

    def _schedule_tables(self, soup: BeautifulSoup) -> list:
        tables = []
        for table in soup.find_all("table"):
            rows = self._direct_rows(table)
            if len(rows) < 2:
                continue
            header_text = " ".join(rows[0])
            detail_text = " ".join(rows[1])
            if "上映期間" in header_text and "片(" in detail_text and "分級" in detail_text:
                tables.append(table)
        return tables

    def _parse_schedule_table(self, table, block_index: int) -> list[ScrapedShowtime]:
        rows = self._direct_rows(table)
        dates = self._date_range(rows[0])
        nested = table.find("table")
        if not nested or not dates:
            return []

        detail_rows = self._direct_rows(nested)
        movies_by_column = self._movies_by_column(detail_rows, table)
        if not movies_by_column:
            return []

        results: list[ScrapedShowtime] = []
        for row in detail_rows:
            for column_index, value in enumerate(row):
                start_time = self._parse_time(value)
                if not start_time:
                    continue
                movie_info = self._movie_for_column(movies_by_column, column_index)
                if not movie_info:
                    continue
                movie, language = movie_info
                for show_date in dates:
                    source_key = (
                        f"ucc:{block_index}:{movie.source_movie_id}:"
                        f"{show_date.isoformat()}:{start_time.strftime('%H:%M')}:"
                        f"{column_index}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=f"第{block_index}廳",
                            format="數位",
                            language=language,
                            booking_url=SCHEDULE_URL,
                            source="ucc",
                            source_showtime_id=source_key,
                            version_label=self._version_label(language),
                            auditorium_brand=None,
                            projection_type="數位",
                            audio_language=language,
                            subtitle_language=None,
                            source_payload={
                                "schedule_url": SCHEDULE_URL,
                                "block_index": block_index,
                                "column_index": column_index,
                            },
                        )
                    )
        return results

    def _movies_by_column(
        self,
        rows: list[list[str]],
        table,
    ) -> dict[int, tuple[ScrapedMovie, str | None]]:
        if not rows:
            return {}
        title_row = rows[0]
        rating_row = self._row_after_label(rows, "分級")
        duration_row = self._row_after_label(rows, "片長")
        poster_url = self._poster_url(table)
        movies: dict[int, tuple[ScrapedMovie, str | None]] = {}

        for index, value in enumerate(title_row[:-1]):
            if "片(" not in value:
                continue
            title = self._clean_text(title_row[index + 1])
            if not title:
                continue
            rating_text = rating_row[index + 1] if rating_row and index + 1 < len(rating_row) else None
            duration_text = duration_row[index + 1] if duration_row and index + 1 < len(duration_row) else None
            rating, language = self._rating_language(rating_text)
            source_movie_id = self._movie_key(title)
            movies[index + 1] = (
                ScrapedMovie(
                    title=title,
                    title_zh=title,
                    poster_url=poster_url,
                    duration_minutes=self._duration_minutes(duration_text),
                    rating=rating,
                    detail_url=SCHEDULE_URL,
                    source_movie_id=source_movie_id,
                ),
                language,
            )
        return movies

    def _date_range(self, header_cells: list[str]) -> list[date]:
        header = " ".join(header_cells)
        year_match = re.search(r"(?P<year>\d{2,3})\s*年", header)
        start_match = re.search(r"(?P<start_month>\d{1,2})\s*月\s*(?P<start_day>\d{1,2})\s*日?\s*至", header)
        end_match = re.search(r"至\s*(?:(?P<end_month>\d{1,2})\s*月)?\s*(?P<end_day>\d{1,2})\s*日?\s*止", header)
        if not year_match or not start_match or not end_match:
            return []

        year = int(year_match.group("year"))
        if year < 1911:
            year += 1911
        start_month = int(start_match.group("start_month"))
        start_day = int(start_match.group("start_day"))
        end_month = int(end_match.group("end_month") or start_month)
        end_day = int(end_match.group("end_day"))
        try:
            start = date(year, start_month, start_day)
            end = date(year, end_month, end_day)
            if end < start:
                end = date(year + 1, end_month, end_day)
        except ValueError:
            return []

        days = (end - start).days
        if days < 0 or days > 31:
            return []
        return [start + timedelta(days=offset) for offset in range(days + 1)]

    def _rating_language(self, value: str | None) -> tuple[str | None, str | None]:
        text = self._clean_text(value) or ""
        rating = None
        if "0普" in text or "普" in text:
            rating = "普遍級"
        elif "6保" in text or "保" in text:
            rating = "保護級"
        elif "12輔" in text:
            rating = "輔12級"
        elif "15輔" in text:
            rating = "輔15級"
        elif "限" in text:
            rating = "限制級"

        language = None
        if "國語" in text:
            language = "國語"
        elif "英語" in text:
            language = "英語"
        elif "日語" in text:
            language = "日語"
        elif "韓語" in text:
            language = "韓語"
        return rating, language

    def _duration_minutes(self, value: str | None) -> int | None:
        text = self._clean_text(value) or ""
        hour_match = re.search(r"(?P<hour>\d+)\s*時", text)
        minute_match = re.search(r"(?P<minute>\d+)\s*分", text)
        hours = int(hour_match.group("hour")) if hour_match else 0
        minutes = int(minute_match.group("minute")) if minute_match else 0
        total = hours * 60 + minutes
        return total or None

    def _version_label(self, language: str | None) -> str:
        return f"數位({language})" if language else "數位"

    def _movie_for_column(
        self,
        movies_by_column: dict[int, tuple[ScrapedMovie, str | None]],
        column_index: int,
    ) -> tuple[ScrapedMovie, str | None] | None:
        if column_index in movies_by_column:
            return movies_by_column[column_index]
        candidates = [index for index in movies_by_column if index <= column_index]
        return movies_by_column[max(candidates)] if candidates else None

    def _row_after_label(self, rows: list[list[str]], label: str) -> list[str] | None:
        for row in rows:
            if any(cell.strip() == label for cell in row):
                return row
        return None

    def _poster_url(self, table) -> str | None:
        image = table.select_one("img[src]")
        if not image:
            return None
        return urljoin(SITE_BASE_URL, image.get("src") or "")

    def _parse_time(self, value: str | None):
        text = (value or "").replace("：", ":")
        match = re.search(r"(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)", text)
        if not match:
            return None
        hour = int(match.group("hour"))
        if hour > 23:
            return None
        return datetime.strptime(f"{hour:02d}:{match.group('minute')}", "%H:%M").time()

    def _direct_rows(self, table) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.find_all("tr", recursive=False):
            cells = [
                self._clean_text(cell.get_text(" ", strip=True)) or ""
                for cell in row.find_all(["td", "th"], recursive=False)
            ]
            rows.append(cells)
        return rows

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
            raw = response.read()
        for encoding in ["big5", "cp950", "utf-8"]:
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")

    def _clean_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", value).strip()
        return text or None

    def _movie_key(self, title: str | None) -> str:
        if not title:
            return ""
        return re.sub(r"[\W_]+", "", title).lower()

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[tuple[str, str]] = set()
        unique: list[ScrapedShowtime] = []
        for item in items:
            key = (item.source, item.source_showtime_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique
