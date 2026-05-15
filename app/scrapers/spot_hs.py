from __future__ import annotations

import ast
import re
from datetime import date, datetime
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.spot-hs.org.tw"
NOW_PLAYING_URL = f"{SITE_BASE_URL}/movie/nowplaying.html"
BOOKING_URL = "https://spot-hs.tixi.com.tw/"
CHAIN = "SPOT Huashan"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="光點華山電影館",
    city="台北",
    address="台北市中正區八德路一段一號",
    source_cinema_id="spot-huashan",
)


class SpotHuashanScraper:
    """Scraper for SPOT Huashan Film House.

    The site publishes current films as static HTML pages. Each detail page
    embeds a JavaScript MovieSchedule array containing the active showtimes.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for movie_url in self._movie_urls():
            try:
                results.extend(self._scrape_movie(movie_url))
            except Exception:
                continue
        return self._dedupe(results)

    def _movie_urls(self) -> list[str]:
        soup = BeautifulSoup(self._fetch_text(NOW_PLAYING_URL), "lxml")
        urls: list[str] = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            if not re.search(r"movie\d{6}/movie\d{8}\.html$", href):
                continue
            absolute = urljoin(NOW_PLAYING_URL, href)
            if absolute not in urls:
                urls.append(absolute)
        return urls

    def _scrape_movie(self, url: str) -> list[ScrapedShowtime]:
        html = self._fetch_text(url)
        soup = BeautifulSoup(html, "lxml")
        movie = self._movie_from_page(soup, url)
        audio_language = self._movie_meta(soup).get("發音")
        subtitle_language = self._movie_meta(soup).get("字幕")

        results: list[ScrapedShowtime] = []
        for index, show in enumerate(self._schedule_from_html(html), start=1):
            note = show["note"]
            version_label = "數位" if not note else f"數位 {note}"
            source_key = (
                f"spot_hs:{movie.source_movie_id}:{show['date'].isoformat()}:"
                f"{show['time'].strftime('%H:%M')}:{show['hall'] or ''}:{index}"
            )
            results.append(
                ScrapedShowtime(
                    cinema=CINEMA,
                    movie=movie,
                    show_date=show["date"],
                    start_time=show["time"],
                    hall_name=show["hall"],
                    format="數位",
                    language=audio_language,
                    booking_url=BOOKING_URL,
                    source="spot_hs",
                    source_showtime_id=source_key,
                    version_label=version_label,
                    auditorium_brand=None,
                    projection_type="數位",
                    audio_language=audio_language,
                    subtitle_language=subtitle_language,
                    source_payload={
                        "movie_url": url,
                        "raw_showtime": show["raw"],
                    },
                )
            )
        return results

    def _movie_from_page(self, soup: BeautifulSoup, url: str) -> ScrapedMovie:
        meta = self._movie_meta(soup)
        title_zh = self._first_text(soup, ".MDpart01_1")
        title_en = self._first_text(soup, ".MDpart01_2")
        poster_url = self._first_image_url(soup, ".MDpartDiv2 img[src]", url)
        still_urls = self._image_urls(soup, ".moviedetail img[src]", url)
        release_date = self._release_date(self._first_text(soup, ".MDpart03_1"))
        trailer_url = self._trailer_url(soup, url)
        return ScrapedMovie(
            title=title_zh or title_en or self._source_movie_id(url),
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=poster_url,
            still_urls=still_urls or None,
            release_date=release_date,
            duration_minutes=self._runtime(meta.get("片長")),
            rating=self._rating(self._first_text(soup, ".MDpart03_3")),
            description=self._description(soup),
            director=meta.get("導演"),
            trailer_url=trailer_url,
            detail_url=url,
            source_movie_id=self._source_movie_id(url),
        )

    def _schedule_from_html(self, html: str) -> list[dict]:
        match = re.search(r"var\s+MovieSchedule\s*=\s*(\[[\s\S]*?\])\s*;", html)
        if not match:
            return []

        rows = self._literal_schedule(match.group(1))
        today = date.today()
        schedule: list[dict] = []
        for row in rows:
            if not row or len(row) < 2:
                continue
            show_date = self._parse_date(str(row[0]))
            if not show_date or show_date < today:
                continue
            for raw_value in row[1:]:
                show = self._parse_showtime(str(raw_value), show_date)
                if show:
                    schedule.append(show)
        return schedule

    def _literal_schedule(self, value: str) -> list[list[str]]:
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [row for row in parsed if isinstance(row, list)]
        except (SyntaxError, ValueError):
            pass

        rows: list[list[str]] = []
        for row_text in re.findall(r"\[(.*?)\]", value, re.DOTALL):
            row = re.findall(r"'([^']*)'", row_text)
            if row:
                rows.append(row)
        return rows

    def _parse_showtime(self, raw_value: str, show_date: date) -> dict | None:
        text = BeautifulSoup(raw_value.replace("<br>", " "), "lxml").get_text(" ", strip=True)
        text = self._clean_text(text)
        if not text:
            return None

        match = re.search(r"(?P<time>\d{1,2}:\d{2})(?P<body>.*)", text)
        if not match:
            return None

        start_time = datetime.strptime(match.group("time"), "%H:%M").time()
        body = match.group("body").strip()
        hall = self._hall_name(body)
        note = body
        if hall:
            note = note.replace(hall, "", 1).strip()
        return {
            "date": show_date,
            "time": start_time,
            "hall": hall,
            "note": note or None,
            "raw": raw_value,
        }

    def _hall_name(self, value: str | None) -> str | None:
        if not value:
            return None
        match = re.search(r"A\s*(?:One|Two|1|2)\s*廳", value, re.IGNORECASE)
        if not match:
            match = re.search(r"[^\s]+廳", value)
        if not match:
            return None
        return self._clean_text(match.group(0))

    def _movie_meta(self, soup: BeautifulSoup) -> dict[str, str]:
        values: dict[str, str] = {}
        for node in soup.select(".MDpart02_1"):
            text = self._clean_text(node.get_text(" ", strip=True))
            if not text or ":" not in text:
                continue
            key, value = text.split(":", 1)
            values[key.strip()] = value.strip()
        return values

    def _description(self, soup: BeautifulSoup) -> str | None:
        label = soup.find(["h5", "h4"], string=re.compile("劇情介紹|Story", re.IGNORECASE))
        if not label:
            return None

        texts: list[str] = []
        for node in label.find_all_next(["div", "p"], limit=10):
            classes = set(node.get("class") or [])
            if not classes.intersection({"MDStory2", "MDStory3"}):
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                texts.append(text)
        return "\n\n".join(dict.fromkeys(texts)) or None

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
            return response.read().decode("utf-8", errors="ignore")

    def _first_text(self, soup: BeautifulSoup, selector: str) -> str | None:
        for node in soup.select(selector):
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                return text
        return None

    def _first_image_url(self, soup: BeautifulSoup, selector: str, page_url: str) -> str | None:
        urls = self._image_urls(soup, selector, page_url)
        return urls[0] if urls else None

    def _image_urls(self, soup: BeautifulSoup, selector: str, page_url: str) -> list[str]:
        urls: list[str] = []
        for image in soup.select(selector):
            src = image.get("src")
            if not src:
                continue
            absolute = urljoin(page_url, src)
            if absolute not in urls:
                urls.append(absolute)
        return urls

    def _trailer_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        iframe = soup.select_one('iframe[src*="youtube.com/embed"], iframe[src*="youtu.be"]')
        if iframe and iframe.get("src"):
            return urljoin(page_url, iframe["src"])
        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""
            if "youtube.com" in href or "youtu.be" in href:
                return href
        return None

    def _source_movie_id(self, url: str) -> str:
        match = re.search(r"/movie(\d{6})/(movie\d{8})\.html$", url)
        if not match:
            return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
        return f"{match.group(1)}-{match.group(2)}"

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", value)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _release_date(self, value: str | None) -> date | None:
        return self._parse_date(value)

    def _runtime(self, value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"(\d{2,3})\s*min", value, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.replace(" ", "")
        if "限" in text or "18" in text:
            return "限制級"
        if "輔15" in text:
            return "輔15級"
        if "輔12" in text:
            return "輔12級"
        if "護" in text or "6+" in text:
            return "保護級"
        if "普" in text:
            return "普遍級"
        return value

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
