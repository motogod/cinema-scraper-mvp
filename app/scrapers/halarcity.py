from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://halarcity.com.tw"
BRAND_BASE_URL = "http://www.halarcity.com"
SCHEDULE_URL = f"{SITE_BASE_URL}/browsing/Cinemas/Details/0000000001"
CHAIN = "Halar Cinemas"
CINEMA = ScrapedCinema(
    chain=CHAIN,
    name="哈拉影城",
    city="台北",
    address="台北市內湖區康寧路三段72號",
    source_cinema_id="0000000001",
)


@dataclass(frozen=True)
class HalarMovieIndex:
    title_zh: str | None = None
    title_en: str | None = None
    release_date: date | None = None
    poster_url: str | None = None
    detail_url: str | None = None


class HalarCityScraper:
    """Scraper for Halar Cinemas.

    Halar uses a Vista schedule page on `halarcity.com.tw`, while richer movie
    metadata lives on the brand site `www.halarcity.com`.
    """

    def scrape(self) -> list[ScrapedShowtime]:
        movie_index = self._movie_index()
        detail_cache: dict[str, ScrapedMovie] = {}
        soup = BeautifulSoup(self._fetch_text(SCHEDULE_URL), "lxml")
        results: list[ScrapedShowtime] = []

        for item in soup.select(".film-list .film-item[data-film-ho-code]"):
            movie = self._movie_from_item(item, movie_index, detail_cache)
            version_prefix = self._title_prefix(self._first_text(item, ".film-title"))
            for session in item.select(".session"):
                show_date = self._parse_date(self._first_text(session, ".session-date"))
                if not show_date:
                    continue
                for anchor in session.select("a.session-time"):
                    time_node = anchor.select_one("time")
                    start_dt = self._parse_datetime(time_node.get("datetime") if time_node else None)
                    start_time = start_dt.time() if start_dt else self._parse_time(anchor.get_text(" ", strip=True))
                    if not start_time:
                        continue

                    attribute = self._session_attribute(anchor)
                    version = self._version_label(attribute, version_prefix)
                    session_id = self._session_id(anchor.get("href"))
                    source_key = (
                        f"halarcity:{movie.source_movie_id}:{session_id or ''}:"
                        f"{show_date.isoformat()}:{start_time.strftime('%H:%M')}"
                    )
                    results.append(
                        ScrapedShowtime(
                            cinema=CINEMA,
                            movie=movie,
                            show_date=show_date,
                            start_time=start_time,
                            hall_name=attribute,
                            format=version,
                            language=self._audio_language(version_prefix),
                            booking_url=urljoin(SITE_BASE_URL, anchor.get("href") or ""),
                            source="halarcity",
                            source_showtime_id=source_key,
                            version_label=version,
                            auditorium_brand=attribute,
                            projection_type="數位",
                            audio_language=self._audio_language(version_prefix),
                            subtitle_language=None,
                            source_payload={
                                "schedule_url": SCHEDULE_URL,
                                "session_id": session_id,
                                "attribute": attribute,
                                "title_prefix": version_prefix,
                            },
                        )
                    )
        return self._dedupe(results)

    def _movie_from_item(
        self,
        item,
        movie_index: dict[str, HalarMovieIndex],
        detail_cache: dict[str, ScrapedMovie],
    ) -> ScrapedMovie:
        raw_title = self._first_text(item, ".film-title")
        title = self._clean_title(raw_title)
        source_movie_id = item.get("data-film-ho-code") or item.get("data-movie-id") or self._movie_key(title)
        detail_url = self._detail_url(item)
        index = movie_index.get(self._movie_key(title), HalarMovieIndex())
        if index.detail_url and index.detail_url not in detail_cache:
            try:
                detail_cache[index.detail_url] = self._movie_from_brand_detail(index.detail_url, title, source_movie_id)
            except Exception:
                detail_cache[index.detail_url] = self._basic_movie(item, title, source_movie_id, detail_url, index)

        movie = detail_cache.get(index.detail_url or "")
        if movie:
            return ScrapedMovie(
                **{
                    **movie.__dict__,
                    "source_movie_id": source_movie_id,
                    "poster_url": movie.poster_url or self._poster_url(item) or index.poster_url,
                    "detail_url": movie.detail_url or index.detail_url or detail_url,
                }
            )
        return self._basic_movie(item, title, source_movie_id, detail_url, index)

    def _basic_movie(
        self,
        item,
        title: str | None,
        source_movie_id: str,
        detail_url: str | None,
        index: HalarMovieIndex,
    ) -> ScrapedMovie:
        return ScrapedMovie(
            title=title or index.title_zh or source_movie_id,
            title_zh=title or index.title_zh,
            title_en=index.title_en,
            original_title=index.title_en,
            poster_url=self._poster_url(item) or index.poster_url,
            release_date=index.release_date,
            rating=self._rating_from_item(item),
            detail_url=index.detail_url or detail_url,
            source_movie_id=source_movie_id,
        )

    def _movie_from_brand_detail(self, url: str, fallback_title: str | None, source_movie_id: str) -> ScrapedMovie:
        soup = BeautifulSoup(self._fetch_text(url), "lxml")
        title_zh = (
            self._first_text(soup, ".movie-banner__title")
            or self._first_text(soup, ".movie-info__title h2")
            or fallback_title
        )
        title_en = self._first_text(soup, ".movie-banner__subtitle") or self._first_text(soup, ".movie-info__title h3")
        if not title_en:
            title_en = self._english_title_near_main_title(soup, title_zh)
        meta = self._brand_movie_meta(soup)
        poster_url = self._first_image_url(soup, url)
        return ScrapedMovie(
            title=title_zh or title_en or source_movie_id,
            title_zh=title_zh,
            title_en=title_en,
            original_title=title_en,
            poster_url=poster_url,
            release_date=self._parse_release_date(meta.get("release_date")),
            duration_minutes=self._parse_int(meta.get("duration")),
            rating=self._rating(meta.get("rating")),
            genre=meta.get("genre"),
            description=self._description(soup),
            director=meta.get("director"),
            cast=meta.get("cast"),
            trailer_url=self._trailer_url(soup, url),
            detail_url=url,
            source_movie_id=source_movie_id,
        )

    def _movie_index(self) -> dict[str, HalarMovieIndex]:
        index: dict[str, HalarMovieIndex] = {}
        for url in [
            BRAND_BASE_URL,
            f"{BRAND_BASE_URL}/movie/catalog/category/9/page/1",
            f"{BRAND_BASE_URL}/movie/catalog/category/10/page/1",
            f"{BRAND_BASE_URL}/movie/catalog/category/11/page/1",
            f"{BRAND_BASE_URL}/movie/catalog/category/24/page/1",
        ]:
            try:
                soup = BeautifulSoup(self._fetch_text(url), "lxml")
            except Exception:
                continue
            self._merge_home_index(index, soup)
            self._merge_catalog_index(index, soup)
        return index

    def _merge_home_index(self, index: dict[str, HalarMovieIndex], soup: BeautifulSoup) -> None:
        for node in soup.select(".indexhot__item"):
            title_zh = self._first_text(node, ".indexhot__item-title h3")
            title_en = self._first_text(node, ".indexhot__item-entitle p")
            detail = self._anchor_url(node, 'a.indexhot__item-head[href]', BRAND_BASE_URL)
            poster = self._background_url(node.select_one(".indexhot__item-img"), BRAND_BASE_URL)
            self._put_index(index, title_zh, title_en, None, poster, detail)

    def _merge_catalog_index(self, index: dict[str, HalarMovieIndex], soup: BeautifulSoup) -> None:
        for node in soup.select(".indexmovies__item, .movie-list__item, .movie__item"):
            title_zh = self._first_text(node, "h2")
            title_en = self._first_text(node, "h3")
            release_date = self._parse_release_date(self._first_text(node, "p"))
            detail = self._anchor_url(node, "a[href]", BRAND_BASE_URL)
            poster = self._background_url(node.select_one('[style*="background-image"]'), BRAND_BASE_URL)
            self._put_index(index, title_zh, title_en, release_date, poster, detail)

    def _put_index(
        self,
        index: dict[str, HalarMovieIndex],
        title_zh: str | None,
        title_en: str | None,
        release_date: date | None,
        poster_url: str | None,
        detail_url: str | None,
    ) -> None:
        key = self._movie_key(title_zh)
        if not key:
            return
        current = index.get(key, HalarMovieIndex())
        index[key] = HalarMovieIndex(
            title_zh=title_zh or current.title_zh,
            title_en=title_en or current.title_en,
            release_date=release_date or current.release_date,
            poster_url=poster_url or current.poster_url,
            detail_url=detail_url or current.detail_url,
        )

    def _brand_movie_meta(self, soup: BeautifulSoup) -> dict[str, str | None]:
        meta: dict[str, str | None] = {}
        meta["duration"] = self._first_text(soup, ".movie-banner__minute")
        meta["release_date"] = self._first_text(soup, ".movie-banner__date")
        meta["rating"] = self._first_text(soup, ".movie-banner__level span")

        for row in soup.select(".movie-banner__detail-row"):
            values = [self._clean_text(node.get_text(" ", strip=True)) for node in row.select("p")]
            values = [value for value in values if value]
            if len(values) < 2:
                continue
            key = values[0].rstrip("：:")
            value = values[1]
            if key == "導演":
                meta["director"] = value
            elif key == "演員":
                meta["cast"] = value
            elif key == "類型":
                meta["genre"] = value
            elif key == "發音":
                meta["audio_language"] = value
        if meta:
            return meta

        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line == "導演：" and index + 1 < len(lines):
                meta["director"] = lines[index + 1]
            elif line == "演員：" and index + 1 < len(lines):
                meta["cast"] = lines[index + 1]
            elif line == "類型：" and index + 1 < len(lines):
                meta["genre"] = lines[index + 1]
            elif line == "發音：" and index + 1 < len(lines):
                meta["audio_language"] = lines[index + 1]

        duration_match = re.search(r"\n(?P<duration>\d{2,3})\n片長\s*/\s*分", text)
        if duration_match:
            meta["duration"] = duration_match.group("duration")
        rating_match = re.search(r"\n(?P<rating>普|護|輔\s*\d{0,2}|限)\s*\d*\n(?P<release>\d{4}/\d{2}/\d{2})", text)
        if rating_match:
            meta["rating"] = rating_match.group("rating")
            meta["release_date"] = rating_match.group("release")
        return meta

    def _description(self, soup: BeautifulSoup) -> str | None:
        about = self._first_text(soup, ".movie-body__about")
        if about:
            return about
        heading = soup.find(string=re.compile(r"劇情介紹"))
        if heading:
            parts: list[str] = []
            for node in heading.find_all_next(string=True, limit=30):
                text = self._clean_text(str(node))
                if not text:
                    continue
                if "精采預告" in text or "返回列表" in text:
                    break
                if text in {"分享：", "MOVIE SYNOPSIS"}:
                    continue
                parts.append(text)
            return "\n".join(parts).strip() or None
        return self._first_text(soup, ".boxout-blurb")

    def _english_title_near_main_title(self, soup: BeautifulSoup, title_zh: str | None) -> str | None:
        if not title_zh:
            return None
        lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line == title_zh and index + 1 < len(lines):
                candidate = lines[index + 1]
                if re.search(r"[A-Za-z]", candidate) and not re.search(r"[\u4e00-\u9fff]", candidate):
                    return candidate
        return None

    def _detail_url(self, item) -> str | None:
        return self._anchor_url(item, ".film-header a[href]", SITE_BASE_URL)

    def _poster_url(self, item) -> str | None:
        image = item.select_one(".movie-image img[src]:not(.rating-image)")
        return urljoin(SITE_BASE_URL, image.get("src") or "") if image else None

    def _rating_from_item(self, item) -> str | None:
        image = item.select_one("img.rating-image[src]")
        if not image:
            return None
        src = image.get("src") or ""
        match = re.search(r"RatingIconGraphic/([^?]+)", src)
        return self._rating(match.group(1)) if match else None

    def _session_attribute(self, anchor) -> str | None:
        image = anchor.select_one("img[alt]")
        return self._clean_text(image.get("alt")) if image else None

    def _version_label(self, attribute: str | None, prefix: str | None) -> str | None:
        parts = [part for part in [attribute, prefix] if part]
        return " ".join(parts) or "數位"

    def _title_prefix(self, title: str | None) -> str | None:
        match = re.match(r"^\((?P<prefix>[^)]+)\)", title or "")
        return match.group("prefix") if match else None

    def _clean_title(self, title: str | None) -> str | None:
        return self._clean_text(re.sub(r"^\([^)]+\)", "", title or ""))

    def _audio_language(self, prefix: str | None) -> str | None:
        if not prefix:
            return None
        if "中" in prefix or "國" in prefix:
            return "中文"
        if "英" in prefix:
            return "英語"
        if "日" in prefix:
            return "日語"
        return None

    def _session_id(self, href: str | None) -> str | None:
        if not href:
            return None
        query = parse_qs(urlparse(href).query)
        values = query.get("txtSessionId")
        return values[0] if values else None

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _parse_date(self, value: str | None) -> date | None:
        match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value or "")
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _parse_release_date(self, value: str | None) -> date | None:
        match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value or "")
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _parse_time(self, value: str | None):
        match = re.search(r"\d{1,2}:\d{2}", value or "")
        if not match:
            return None
        return datetime.strptime(match.group(0), "%H:%M").time()

    def _parse_int(self, value: str | None) -> int | None:
        match = re.search(r"\d+", value or "")
        return int(match.group(0)) if match else None

    def _rating(self, value: str | None) -> str | None:
        if not value:
            return None
        text = self._clean_text(unquote(value)) or ""
        mapping = {
            "普": "普遍級",
            "普遍級": "普遍級",
            "護": "保護級",
            "保護級": "保護級",
            "輔": "輔導級",
            "輔12": "輔12級",
            "輔12級": "輔12級",
            "輔15": "輔15級",
            "輔15級": "輔15級",
            "限": "限制級",
            "限制級": "限制級",
        }
        if text in mapping:
            return mapping[text]
        for key, rating in mapping.items():
            if key and key in text:
                return rating
        return text or None

    def _trailer_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        iframe = soup.select_one("iframe[src]")
        if iframe:
            return urljoin(base_url, iframe.get("src") or "")
        embed = soup.select_one("embed[src]")
        if embed:
            return urljoin(base_url, embed.get("src") or "")
        return None

    def _first_image_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        node = soup.select_one(".movie-banner__img img[src], .movie-detail img[src], .movie-info img[src], img[alt][src]")
        if not node:
            return None
        return urljoin(base_url, node.get("src") or "")

    def _background_url(self, node, base_url: str) -> str | None:
        if not node:
            return None
        match = re.search(r"url\((?P<quote>['\"]?)(?P<url>.*?)(?P=quote)\)", node.get("style") or "")
        return urljoin(base_url, match.group("url")) if match else None

    def _anchor_url(self, node, selector: str, base_url: str) -> str | None:
        anchor = node.select_one(selector)
        if not anchor:
            return None
        return urljoin(base_url, anchor.get("href") or "")

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
        context = ssl._create_unverified_context() if url.startswith("https://") else None
        with urlopen(request, timeout=60, context=context) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _first_text(self, node, selector: str) -> str | None:
        found = node.select_one(selector)
        return self._clean_text(found.get_text(" ", strip=True)) if found else None

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
