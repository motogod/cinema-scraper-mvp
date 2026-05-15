from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

SITE_BASE_URL = "https://www.in89cinemax.com"
CHAIN = "in89 Cinemax"

FALLBACK_THEATERS = [
    ("3", "台北西門_in89豪華影城"),
    ("1", "桃園站前_in89豪華影城"),
    ("15", "台中豐原_in89豪華影城"),
    ("17", "嘉義影食匯_in89豪華影城"),
    ("2", "高雄鹽埕_in89駁二電影院"),
    ("16", "高雄大立_in89豪華影城"),
    ("14", "澎湖昇恆昌_in89豪華影城"),
]


@dataclass(frozen=True)
class TheaterConfig:
    page_id: str
    name: str
    api_host: str
    address: str | None = None


class In89Scraper:
    """Scraper for in89 Cinemax.

    in89's pages render schedules from per-theater API hosts. The public page
    exposes each host in a hidden `theater_api` field, then the frontend calls
    `api_movie.php` methods such as `getStagesByDate`.
    """

    def __init__(self, enrich_details: bool = False):
        self.enrich_details = enrich_details

    def scrape(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        for theater in self._discover_theaters():
            try:
                results.extend(self._scrape_theater(theater))
            except Exception:
                continue
        return results

    def _discover_theaters(self) -> list[TheaterConfig]:
        theater_options = self._theater_options()
        configs: list[TheaterConfig] = []
        for page_id, fallback_name in theater_options:
            try:
                page_html = self._fetch_text(f"{SITE_BASE_URL}/index.aspx?TheaterId={page_id}")
            except Exception:
                continue
            soup = BeautifulSoup(page_html, "lxml")
            api_host = self._input_value(soup, "theater_api")
            if not api_host:
                continue
            name = self._input_value(soup, "TheaterName") or self._page_title(soup) or fallback_name
            configs.append(
                TheaterConfig(
                    page_id=page_id,
                    name=name,
                    api_host=api_host,
                    address=self._address_from_page(soup),
                )
            )
        return configs

    def _theater_options(self) -> list[tuple[str, str]]:
        try:
            soup = BeautifulSoup(self._fetch_text(SITE_BASE_URL), "lxml")
        except Exception:
            return FALLBACK_THEATERS

        options: list[tuple[str, str]] = []
        for option in soup.select("option[value]"):
            value = (option.get("value") or "").strip()
            name = option.get_text(strip=True)
            if value.isdigit() and name:
                options.append((value, name))
        return options or FALLBACK_THEATERS

    def _scrape_theater(self, theater: TheaterConfig) -> list[ScrapedShowtime]:
        schedule = self._api(theater.api_host, "getStagesByDate")
        movies = schedule.get("movies") or {}
        stages = self._collect_stages(schedule.get("stages") or {})
        if not stages:
            return []

        details = self._movie_details_by_id(theater, movies, stages) if self.enrich_details else {}
        cinema = ScrapedCinema(
            chain=CHAIN,
            name=theater.name,
            city=self._city_from_address(theater.address) or self._city_from_name(theater.name),
            address=theater.address,
            source_cinema_id=theater.page_id,
        )

        results: list[ScrapedShowtime] = []
        for stage in stages:
            show_at = self._parse_datetime(stage.get("movie_show_time"))
            if not show_at:
                continue

            movie_id = str(stage.get("movie_id") or "")
            movie_meta = self._as_dict(details.get(movie_id)) or self._as_dict(movies.get(movie_id))
            if not movie_meta:
                continue

            format_info = self._format_info(movie_meta, stage)
            movie = self._movie_from_meta(theater, movie_meta)
            results.append(
                ScrapedShowtime(
                    cinema=cinema,
                    movie=movie,
                    show_date=show_at.date(),
                    start_time=show_at.time().replace(second=0, microsecond=0),
                    hall_name=stage.get("theater_film_name") or None,
                    format=format_info["format"],
                    language=format_info["language"],
                    booking_url=f"{SITE_BASE_URL}/film_list.aspx?TheaterId={theater.page_id}",
                    source="in89",
                    source_showtime_id=f"in89:{theater.page_id}:{stage.get('stage_id')}",
                    version_label=format_info["version_label"],
                    auditorium_brand=format_info["auditorium_brand"],
                    projection_type=format_info["projection_type"],
                    audio_language=format_info["language"],
                    subtitle_language="英文" if movie_meta.get("en_subtitle") == "1" else None,
                    source_payload={
                        "theater": {
                            "page_id": theater.page_id,
                            "api_host": theater.api_host,
                            "name": theater.name,
                        },
                        "stage": stage,
                    },
                )
            )
        return results

    def _movie_details_by_id(
        self,
        theater: TheaterConfig,
        movies: dict,
        stages: list[dict],
    ) -> dict[str, dict]:
        staged_movie_ids = {str(stage.get("movie_id")) for stage in stages}
        group_ids = {
            str(movie.get("movie_group_id"))
            for movie_id, movie in movies.items()
            if str(movie_id) in staged_movie_ids
            and self._as_dict(movie).get("movie_group_id")
        }
        details: dict[str, dict] = {}
        for group_id in sorted(group_ids):
            try:
                payload = self._api(
                    theater.api_host,
                    "getStagesByMovieGroup",
                    {"movie_group_id": group_id},
                )
            except Exception:
                continue
            for movie in payload.get("movies") or []:
                movie_id = str(movie.get("movie_id") or "")
                if movie_id:
                    details[movie_id] = movie
        return details

    def _movie_from_meta(self, theater: TheaterConfig, movie: dict) -> ScrapedMovie:
        movie_id = self._text(movie.get("movie_id"))
        group_id = self._text(movie.get("movie_group_id")) or movie_id
        title = self._clean_text(movie.get("movie_group_name") or movie.get("cn_name"))
        title_zh = self._clean_text(movie.get("cn_name") or movie.get("movie_group_name"))
        title_en = self._clean_text(movie.get("en_name"))
        return ScrapedMovie(
            title=title or title_zh or f"in89 Movie {group_id}",
            title_zh=title_zh or title,
            title_en=title_en,
            original_title=title_en,
            poster_url=self._image_url(theater.api_host, movie),
            release_date=self._parse_date(movie.get("start_time")),
            duration_minutes=self._parse_int(movie.get("play_duration")),
            rating=self._clean_text(movie.get("movie_age_desc")),
            genre=self._genre_text(movie.get("movie_type_desc")),
            description=self._html_text(movie.get("cn_note")),
            director=self._clean_text(movie.get("director")),
            cast=self._clean_text(movie.get("actors")),
            trailer_url=self._trailer_url(movie.get("trailerlink")),
            detail_url=self._detail_url(theater.page_id, movie_id),
            source_movie_id=f"{theater.page_id}:{group_id}" if group_id else None,
        )

    def _format_info(self, movie: dict, stage: dict) -> dict[str, str | None]:
        play = self._clean_text(stage.get("movie_play_desc") or movie.get("movie_play_desc"))
        language = self._language(movie.get("movie_lang_desc") or stage.get("movie_lang_desc"))
        hall_name = self._clean_text(stage.get("theater_film_name"))
        attributes = self._clean_text(stage.get("attributes"))
        brand = self._auditorium_brand(hall_name, attributes)
        label_base = brand or play
        short_language = self._short_language(language)
        version_label = (
            f"{label_base}({short_language})" if label_base and short_language else label_base or play
        )

        upper_play = (play or "").upper()
        projection_type = None
        if "3D" in upper_play:
            projection_type = "3D"
        elif "2D" in upper_play or "數位" in (play or ""):
            projection_type = "數位"
        elif play:
            projection_type = play

        return {
            "format": play,
            "language": language,
            "version_label": version_label,
            "auditorium_brand": brand,
            "projection_type": projection_type,
        }

    def _auditorium_brand(self, hall_name: str | None, attributes: str | None) -> str | None:
        text = f"{hall_name or ''} {attributes or ''}".upper()
        for token, brand in [
            ("IMAX", "IMAX"),
            ("LUXE", "LUXE"),
            ("MX4D", "MX4D"),
            ("BOOM", "BOOM"),
            ("COACH", "COACH"),
            ("FAMILY", "親子小燈場"),
        ]:
            if token in text:
                return brand
        return None

    def _collect_stages(self, value) -> list[dict]:
        if isinstance(value, list):
            stages: list[dict] = []
            for item in value:
                stages.extend(self._collect_stages(item))
            return stages
        if isinstance(value, dict):
            if value.get("stage_id") and value.get("movie_show_time"):
                return [value]
            stages = []
            for item in value.values():
                stages.extend(self._collect_stages(item))
            return stages
        return []

    def _api(self, api_host: str, method: str, payload: dict | None = None) -> dict:
        data = {"method": method, "tk": str(int(time.time() * 1000))}
        data.update(payload or {})
        body = urlencode(data).encode("utf-8")
        request = Request(
            f"https://{api_host}/api/api_movie.php?method={method}",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": f"{SITE_BASE_URL}/",
            },
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")

    def _input_value(self, soup: BeautifulSoup, name: str) -> str | None:
        field = soup.select_one(f"input[name='{name}']")
        value = field.get("value") if field else None
        return value.strip() if value else None

    def _page_title(self, soup: BeautifulSoup) -> str | None:
        title = soup.select_one("title")
        return title.get_text(strip=True) if title else None

    def _address_from_page(self, soup: BeautifulSoup) -> str | None:
        text = soup.get_text("\n", strip=True)
        match = re.search(r"地址[：:]\s*([^\n]+)", text)
        return match.group(1).strip() if match else None

    def _image_url(self, api_host: str, movie: dict) -> str | None:
        for key in ("253_img_path", "125_img_path", "big_img_path", "small_img_path", "img_path"):
            path = movie.get(key)
            if path:
                return f"https://{api_host}{path}"
        return None

    def _detail_url(self, page_id: str, movie_id: str | None) -> str | None:
        if not movie_id:
            return None
        return f"{SITE_BASE_URL}/film_detail.aspx?TheaterId={page_id}&movie_id={movie_id}"

    def _trailer_url(self, value: str | None) -> str | None:
        if not value:
            return None
        text = html.unescape(value).split('"')[0].strip()
        return text or None

    def _html_text(self, value: str | None) -> str | None:
        if not value:
            return None
        text = BeautifulSoup(html.unescape(value), "lxml").get_text("\n", strip=True)
        return text or None

    def _clean_text(self, value) -> str | None:
        if value is None:
            return None
        text = html.unescape(str(value)).strip()
        return text or None

    def _text(self, value) -> str | None:
        return str(value) if value is not None and str(value) != "" else None

    def _as_dict(self, value) -> dict:
        return value if isinstance(value, dict) else {}

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _parse_int(self, value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _genre_text(self, value: str | None) -> str | None:
        text = self._clean_text(value)
        return text.replace(",", "、") if text else None

    def _language(self, value: str | None) -> str | None:
        mapping = {
            "國語": "國語",
            "中文": "國語",
            "英語": "英語",
            "日語": "日語",
            "韓語": "韓語",
            "粵語": "粵語",
            "越南語": "越南語",
            "泰語": "泰語",
            "多元語": "多元語",
        }
        text = self._clean_text(value)
        return mapping.get(text or "", text)

    def _short_language(self, language: str | None) -> str | None:
        mapping = {
            "國語": "國",
            "英語": "英",
            "日語": "日",
            "韓語": "韓",
            "粵語": "粵",
            "越南語": "越",
            "泰語": "泰",
            "多元語": "多元語",
        }
        return mapping.get(language or "")

    def _city_from_name(self, name: str | None) -> str | None:
        if not name:
            return None
        for city in ["台北", "桃園", "台中", "嘉義", "高雄", "澎湖"]:
            if city in name:
                return city
        return None

    def _city_from_address(self, address: str | None) -> str | None:
        if not address:
            return None
        aliases = {
            "台北市": "台北",
            "臺北市": "台北",
            "桃園市": "桃園",
            "台中市": "台中",
            "臺中市": "台中",
            "嘉義市": "嘉義",
            "高雄市": "高雄",
            "澎湖縣": "澎湖",
        }
        for prefix, city in aliases.items():
            if prefix in address:
                return city
        return None
