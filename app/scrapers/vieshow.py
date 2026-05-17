from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from app.core.config import get_settings
from app.scrapers.base import ScrapedCinema, ScrapedMovie, ScrapedShowtime

BASE_URL = "https://www.vscinemas.com.tw"
SHOWTIMES_URL = f"{BASE_URL}/ShowTimes/"
MOVIE_INDEX_URLS = [
    f"{BASE_URL}/film/index.aspx",
    f"{BASE_URL}/film/coming.aspx",
    f"{BASE_URL}/vsweb/film/index.aspx",
    f"{BASE_URL}/vsweb/film/coming.aspx",
]
THEATER_INDEX_URLS = [
    f"{BASE_URL}/theater/index.aspx",
    f"{BASE_URL}/theater/index2.aspx",
]
CHAIN = "Vie Show"

CINEMA_NAME_BY_CODE = {
    "TP": "台北信義威秀影城",
    "MU": "MUVIE CINEMAS 台北松仁",
    "MUC": "MUVIE CINEMAS 台北松仁 (MUCROWN)",
    "NL": "台北南港 LaLaport威秀影城",
    "QS": "台北京站威秀影城",
    "TX": "台北西門威秀影城",
    "BQ": "板橋大遠百威秀影城",
    "GM": "中和環球威秀影城",
    "HU": "新店裕隆城威秀影城",
    "LK": "林口MITSUI OUTLET PARK威秀影城",
    "TY": "桃園統領威秀影城",
    "TG": "桃園桃知道威秀影城",
    "HS": "新竹大遠百威秀影城",
    "HSGC": "新竹大遠百威秀影城 (GC)",
    "BC": "新竹巨城威秀影城",
    "TF": "頭份尚順威秀影城",
    "TZ": "台中大遠百威秀影城",
    "TT01": "MUVIE CINEMAS 台中TIGER CITY",
    "TT02": "MUVIE CINEMAS 台中TIGER CITY (GC)",
    "MM": "台中大魯閣新時代威秀影城",
    "TN": "台南大遠百威秀影城",
    "FC": "台南FOCUS 威秀影城",
    "NF": "台南南紡威秀影城",
    "NFGC": "台南南紡威秀影城 (GC)",
    "KS": "高雄大遠百威秀影城",
    "KSGC": "高雄大遠百威秀影城 (GC)",
    "HL": "花蓮新天堂樂園威秀影城",
}

CINEMA_ADDRESS_BY_CODE = {
    "TP": "台北市信義區松壽路20號",
    "MU": "台北市信義區松仁路58號10樓",
    "MUC": "台北市信義區松仁路58號10樓",
    "NL": "台北市南港區經貿二路131號5樓",
    "QS": "台北市大同區市民大道一段209號5樓",
    "TX": "台北市萬華區漢中街52號8-11樓",
    "BQ": "新北市板橋區新站路28號10樓",
    "GM": "新北市中和區中山路三段122號4樓",
    "HU": "新北市新店區中興路三段70號7樓",
    "LK": "新北市林口區文化三路一段356號3樓",
    "TY": "桃園市桃園區中正路61號9樓",
    "TG": "桃園市桃園區中正路59號5樓",
    "HS": "新竹市西大路323號8樓",
    "HSGC": "新竹市西大路323號8樓",
    "BC": "新竹市中央路229號7樓",
    "TF": "苗栗縣頭份市中央路105號7樓",
    "TZ": "台中市西屯區臺灣大道三段251號13樓",
    "TT01": "台中市西屯區河南路三段120-1號4樓",
    "TT02": "台中市西屯區河南路三段120-1號4樓",
    "MM": "台中市東區復興路四段186號4樓",
    "TN": "台南市東區前鋒路210號6樓",
    "FC": "台南市中西區中山路166號11樓",
    "NF": "台南市東區中華東路一段366號5樓",
    "NFGC": "台南市東區中華東路一段366號5樓",
    "KS": "高雄市苓雅區三多四路21號13樓",
    "KSGC": "高雄市苓雅區三多四路21號13樓",
    "HL": "花蓮縣吉安鄉南濱路一段503號3樓",
}


class VieShowScraper:
    """Vie Show showtime scraper MVP.

    This scraper captures rendered HTML with Playwright and then parses it with
    conservative heuristics. Expect to tune selectors after inspecting the saved
    debug HTML because cinema sites frequently change markup.
    """

    def __init__(self, headless: bool | None = None) -> None:
        self.settings = get_settings()
        self.headless = self.settings.scraper_headless if headless is None else headless
        self.cinema_details: dict[str, ScrapedCinema] = {}

    def scrape(self) -> list[ScrapedShowtime]:
        theater_detail_results = self._scrape_theater_detail_pages()
        try:
            page_html, showtime_html_by_cinema, movie_details = self._fetch_showtime_html(SHOWTIMES_URL)
        except RuntimeError:
            if theater_detail_results:
                return self._dedupe(theater_detail_results)
            raise
        self._write_debug_html(page_html, showtime_html_by_cinema)
        self._raise_if_blocked(page_html)

        if not showtime_html_by_cinema:
            return self._dedupe(
                theater_detail_results + self._parse_showtimes(page_html, movie_details=movie_details)
            )

        results: list[ScrapedShowtime] = list(theater_detail_results)
        cinemas = self._parse_cinema_options(BeautifulSoup(page_html, "lxml"))
        cinemas_by_code = {cinema.source_cinema_id: cinema for cinema in cinemas}
        for cinema_code, html in showtime_html_by_cinema.items():
            self._raise_if_blocked(html)
            cinema = cinemas_by_code.get(cinema_code)
            if not cinema:
                cinema = ScrapedCinema(chain=CHAIN, name=cinema_code, source_cinema_id=cinema_code)
            results.extend(self._parse_showtimes(html, default_cinema=cinema, movie_details=movie_details))
        return self._dedupe(results)

    def _scrape_theater_detail_pages(self) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page(
                locale="zh-TW",
                timezone_id="Asia/Taipei",
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            detail_urls = self._discover_theater_detail_urls(page)
            detail_pages: list[tuple[str, str]] = []
            wanted_movie_keys: set[str] = set()
            for detail_url in detail_urls:
                try:
                    page.goto(detail_url, wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(700)
                    html = page.content()
                    if "Access Denied" in html or "errors.edgesuite.net" in html:
                        continue
                    self._write_theater_detail_debug_html(detail_url, html)
                    detail_pages.append((detail_url, html))
                    wanted_movie_keys.update(self._extract_movie_keys_from_theater_detail_html(html))
                except Exception:
                    continue
            movie_details = self._fetch_movie_details(page, wanted_movie_keys)
            for detail_url, html in detail_pages:
                results.extend(self._parse_theater_detail_showtimes(html, detail_url, movie_details))
            browser.close()
        return self._dedupe(results)

    def _fetch_showtime_html(self, url: str) -> tuple[str, dict[str, str], dict[str, ScrapedMovie]]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page(
                locale="zh-TW",
                timezone_id="Asia/Taipei",
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(1500)
            page_html = page.content()
            self._write_debug_html(page_html, {})
            self._raise_if_blocked(page_html)

            cinema_codes = page.eval_on_selector_all(
                "#CinemaNameTWInfoF option",
                """options => options
                    .map(option => option.value)
                    .filter(value => value && value.trim().length > 0)
                """,
            )
            showtime_html_by_cinema: dict[str, str] = {}
            for cinema_code in cinema_codes:
                html = page.evaluate(
                    """async (cinemaCode) => {
                        const params = new URLSearchParams();
                        params.set("CinemaCode", cinemaCode);
                        const response = await fetch("/ShowTimes/ShowTimes/GetShowTimes", {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                "X-Requested-With": "XMLHttpRequest"
                            },
                            body: params.toString()
                        });
                        return await response.text();
                    }""",
                    cinema_code,
                )
                showtime_html_by_cinema[cinema_code] = html
            self.cinema_details = self._fetch_cinema_details(page)
            wanted_movie_keys = self._extract_movie_keys_from_showtime_html(showtime_html_by_cinema.values())
            movie_details = self._fetch_movie_details(page, wanted_movie_keys)
            browser.close()
            return page_html, showtime_html_by_cinema, movie_details

    def _write_debug_html(self, html: str, showtime_html_by_cinema: dict[str, str]) -> None:
        debug_dir = Path("debug")
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / "vieshow-showtimes.html").write_text(html, encoding="utf-8")
        for cinema_code, showtime_html in showtime_html_by_cinema.items():
            (debug_dir / f"vieshow-showtimes-{cinema_code}.html").write_text(
                showtime_html,
                encoding="utf-8",
            )

    def _write_theater_detail_debug_html(self, url: str, html: str) -> None:
        debug_dir = Path("debug/theater-details")
        debug_dir.mkdir(parents=True, exist_ok=True)
        match = re.search(r"detail(?P<kind>2?)\.aspx\?id=(?P<id>\d+)", url)
        name = f"vieshow-theater-{match.group('kind') or '1'}-{match.group('id')}.html" if match else "vieshow-theater.html"
        (debug_dir / name).write_text(html, encoding="utf-8")

    def _discover_theater_detail_urls(self, page) -> list[str]:
        urls: list[str] = []
        for theater_url in THEATER_INDEX_URLS:
            try:
                page.goto(theater_url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(700)
                html = page.content()
                if "Access Denied" in html or "errors.edgesuite.net" in html:
                    continue
                soup = BeautifulSoup(html, "lxml")
                for anchor in soup.select('a[href*="detail.aspx?id="], a[href*="detail2.aspx?id="]'):
                    href = anchor.get("href")
                    if not href:
                        continue
                    full_url = urljoin(theater_url, href)
                    if "/theater/" in full_url:
                        urls.append(full_url)
            except Exception:
                continue

        urls.extend(
            [
                f"{BASE_URL}/theater/detail.aspx?id={theater_id}"
                for theater_id in range(1, 23)
            ]
        )
        urls.extend(
            [
                f"{BASE_URL}/theater/detail2.aspx?id={theater_id}"
                for theater_id in range(23, 26)
            ]
        )
        return list(dict.fromkeys(urls))

    def _raise_if_blocked(self, html: str) -> None:
        if "Access Denied" not in html and "errors.edgesuite.net" not in html:
            return
        raise RuntimeError(
            "Vie Show returned an Access Denied page. "
            "Try running `python scripts/scrape.py vieshow --no-headless` from your local terminal, "
            "or inspect debug/vieshow-showtimes.html to confirm the block page."
        )

    def _fetch_cinema_details(self, page) -> dict[str, ScrapedCinema]:
        details: dict[str, ScrapedCinema] = {}
        for theater_url in THEATER_INDEX_URLS:
            try:
                page.goto(theater_url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1000)
                html = page.content()
                if "Access Denied" in html or "errors.edgesuite.net" in html:
                    continue
                for cinema in self._parse_theater_index(html):
                    details[self._cinema_key(cinema.name)] = cinema
            except Exception:
                continue

        for code, detail_name in CINEMA_NAME_BY_CODE.items():
            detail = details.get(self._cinema_key(detail_name))
            if detail:
                details[self._cinema_key(detail_name)] = ScrapedCinema(
                    chain=CHAIN,
                    name=detail_name,
                    city=detail.city,
                    address=detail.address,
                    source_cinema_id=code,
                )
        return details

    def _parse_theater_index(self, html: str) -> list[ScrapedCinema]:
        soup = BeautifulSoup(html, "lxml")
        cinemas: list[ScrapedCinema] = []
        for heading in soup.select("h2"):
            name = heading.get_text(" ", strip=True)
            if "威秀影城" not in name and "MUVIE CINEMAS" not in name:
                continue
            address = self._address_after_heading(heading)
            if not address:
                continue
            cinemas.append(
                ScrapedCinema(
                    chain=CHAIN,
                    name=name,
                    city=self._city_from_address(address) or self._guess_city(name),
                    address=address,
                )
            )
        return cinemas

    def _address_after_heading(self, heading) -> str | None:
        parts: list[str] = []
        capturing = False
        for raw_text in heading.find_all_next(string=True, limit=40):
            text = re.sub(r"\s+", " ", raw_text).strip()
            if not text:
                continue
            if "影城地址" in text:
                capturing = True
                text = re.sub(r"^影城地址[：:]\s*", "", text).strip()
                if text:
                    parts.append(text)
                continue
            if not capturing:
                continue
            if "服務專線" in text:
                break
            if text in {"|", "：", ":"}:
                continue
            parts.append(text)
        return " ".join(parts).strip() or None

    def _extract_movie_keys_from_showtime_html(self, html_values) -> set[str]:
        keys: set[str] = set()
        for html in html_values:
            soup = BeautifulSoup(html, "lxml")
            for node in soup.select("strong.LangTW.MovieName, strong.LangEN.MovieName"):
                parsed = self._split_movie_label(node.get_text(" ", strip=True))
                if parsed["title"]:
                    keys.add(self._movie_key(parsed["title"]))
        return keys

    def _fetch_movie_details(self, page, wanted_movie_keys: set[str]) -> dict[str, ScrapedMovie]:
        if not wanted_movie_keys:
            return {}

        detail_urls: list[str] = []
        for index_url in MOVIE_INDEX_URLS:
            try:
                page.goto(index_url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1000)
                html = page.content()
                if "Access Denied" in html or "errors.edgesuite.net" in html:
                    continue
                self._append_detail_urls_from_html(detail_urls, html, index_url, wanted_movie_keys)
            except Exception:
                continue

        details: dict[str, ScrapedMovie] = {}
        visited: set[str] = set()
        index = 0
        while index < len(detail_urls):
            detail_url = detail_urls[index]
            index += 1
            if detail_url in visited:
                continue
            visited.add(detail_url)
            try:
                page.goto(detail_url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1000)
                html = page.content()
                if "Access Denied" in html or "errors.edgesuite.net" in html:
                    continue
                self._append_detail_urls_from_html(detail_urls, html, detail_url, wanted_movie_keys)
                detail = self._parse_movie_detail(html, detail_url)
                detail_keys = [
                    self._movie_key(detail.title),
                    self._movie_key(detail.title_zh),
                    self._movie_key(detail.title_en),
                ]
                matched_wanted_key = self._matching_wanted_movie_key(detail_keys, wanted_movie_keys)
                if matched_wanted_key:
                    details[matched_wanted_key] = detail
                    for key in detail_keys:
                        if key:
                            details[key] = detail
                self._write_debug_movie_detail(detail, html)
                if wanted_movie_keys.issubset(details.keys()):
                    break
            except Exception:
                continue
        return details

    def _append_detail_urls_from_html(
        self,
        detail_urls: list[str],
        html: str,
        page_url: str,
        wanted_movie_keys: set[str],
    ) -> None:
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.select('a[href*="detail.aspx?id="]'):
            href = anchor.get("href")
            if not href:
                continue
            detail_url = urljoin(page_url, href)
            self._append_detail_url(detail_urls, detail_url)
            text = anchor.get_text(" ", strip=True)
            img = anchor.select_one("img")
            if img:
                text = " ".join(part for part in [text, img.get("alt"), img.get("title")] if part)
            if self._text_matches_wanted_movie(text, wanted_movie_keys):
                self._promote_detail_url(detail_urls, detail_url)

        for option in soup.select("select option[value]"):
            value = (option.get("value") or "").strip()
            if not value.isdigit():
                continue
            detail_url = urljoin(page_url, f"/film/detail.aspx?id={value}")
            name = option.get_text(" ", strip=True)
            if self._text_matches_wanted_movie(name, wanted_movie_keys):
                self._promote_detail_url(detail_urls, detail_url)

    def _append_detail_url(self, detail_urls: list[str], detail_url: str) -> None:
        if detail_url not in detail_urls:
            detail_urls.append(detail_url)

    def _promote_detail_url(self, detail_urls: list[str], detail_url: str) -> None:
        if detail_url in detail_urls:
            detail_urls.remove(detail_url)
        detail_urls.insert(0, detail_url)

    def _text_matches_wanted_movie(self, text: str, wanted_movie_keys: set[str]) -> bool:
        for line in re.split(r"\s{2,}|\n", text):
            parsed = self._split_movie_label(line)
            key = self._movie_key(parsed["title"])
            if key and self._matching_wanted_movie_key([key], wanted_movie_keys):
                return True
        return False

    def _matching_wanted_movie_key(
        self,
        candidate_keys: list[str],
        wanted_movie_keys: set[str],
    ) -> str | None:
        for candidate_key in candidate_keys:
            if not candidate_key:
                continue
            if candidate_key in wanted_movie_keys:
                return candidate_key
            for wanted_key in wanted_movie_keys:
                if self._movie_keys_match(candidate_key, wanted_key):
                    return wanted_key
        return None

    def _movie_keys_match(self, left: str, right: str) -> bool:
        if left == right:
            return True
        if len(left) < 4 or len(right) < 4:
            return False

        shorter, longer = sorted([left, right], key=len)
        if shorter not in longer:
            return False

        # Avoid matching very short common fragments while still accepting
        # showtime labels that are truncated by the Vie Show page.
        return len(shorter) >= 8 or len(shorter) / len(longer) >= 0.55

    def _write_debug_movie_detail(self, movie: ScrapedMovie, html: str) -> None:
        if not movie.source_movie_id:
            return
        debug_dir = Path("debug/movie-details")
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"vieshow-movie-{movie.source_movie_id}.html").write_text(html, encoding="utf-8")

    def _parse_movie_detail(self, html: str, detail_url: str) -> ScrapedMovie:
        soup = BeautifulSoup(html, "lxml")
        lines = self._text_lines(soup)
        title_zh = self._first_heading_text(soup, [".movieMain h1", "h1", ".LangTW", ".title"]) or ""
        title_en = self._first_heading_text(soup, [".movieMain h2", "h2", ".LangEN"])
        if title_zh:
            title_zh = self._split_movie_label(title_zh)["title"] or title_zh
        if title_en:
            title_en = self._split_movie_label(title_en)["title"] or title_en

        poster_url = self._extract_poster_url(soup, detail_url)
        still_urls = self._extract_still_urls(soup, detail_url)
        trailer_url = self._extract_trailer_url(soup, detail_url)
        source_movie_id = self._source_movie_id(detail_url)
        duration = self._parse_duration(self._field_from_detail_table(soup, "片長") or self._field_from_lines(lines, "片長"))
        release_date = self._parse_release_date(self._release_date_text(soup))
        cast_photo_urls = [url for url in still_urls if re.search(r"cast|actor|staff|people", url, re.IGNORECASE)]

        return ScrapedMovie(
            title=title_zh or title_en or detail_url,
            title_zh=title_zh or None,
            title_en=title_en or None,
            original_title=title_en or None,
            poster_url=poster_url,
            still_urls=still_urls or None,
            release_date=release_date,
            duration_minutes=duration,
            rating=self._rating_from_dom(soup) or self._field_from_lines(lines, "分級"),
            genre=self._field_from_detail_table(soup, "類型") or self._field_from_lines(lines, "類型"),
            description=self._description_from_dom(soup) or self._description_from_lines(lines),
            director=self._field_from_detail_table(soup, "導演") or self._field_from_lines(lines, "導演"),
            cast=self._field_from_detail_table(soup, "演員") or self._field_from_lines(lines, "演員"),
            cast_photo_urls=cast_photo_urls or None,
            trailer_url=trailer_url,
            detail_url=detail_url,
            source_movie_id=source_movie_id,
        )

    def _rating_from_dom(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one(".markArea span[class]")
        if not node:
            return None
        classes = node.get("class") or []
        mapping = {
            "general": "普遍級",
            "childview": "保護級",
            "bigchild": "輔12級",
            "teenager": "輔15級",
            "adult": "限制級",
            "needCheck": "待定",
        }
        for class_name in classes:
            if class_name in mapping:
                return mapping[class_name]
        return None

    def _parse_showtimes(
        self,
        html: str,
        default_cinema: ScrapedCinema | None = None,
        movie_details: dict[str, ScrapedMovie] | None = None,
    ) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(html, "lxml")
        cinemas = self._parse_cinema_options(soup)
        if not default_cinema:
            default_cinema = cinemas[0] if cinemas else ScrapedCinema(chain=CHAIN, name="Unknown Vie Show")

        results: list[ScrapedShowtime] = []
        for tw_node in soup.select("strong.LangTW.MovieName"):
            block = tw_node.find_parent("div", class_="col-xs-12")
            if not block:
                continue
            en_node = tw_node.find_next_sibling("strong", class_=lambda value: value and "LangEN" in value)
            movie, showtime_format, language = self._movie_from_labels(
                tw_node.get_text(" ", strip=True),
                en_node.get_text(" ", strip=True) if en_node else None,
                movie_details or {},
            )
            for date_node in block.select("strong.LangTW.RealShowDate"):
                show_date = self._parse_tw_date(date_node.get_text(" ", strip=True))
                if not show_date:
                    continue
                session_node = date_node.find_next_sibling("div", class_="SessionTimeInfo")
                if not session_node:
                    continue
                for time_match in re.finditer(
                    r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)",
                    session_node.get_text(" ", strip=True),
                ):
                    start_time = time(int(time_match.group("hour")), int(time_match.group("minute")))
                    results.append(
                        self._build_showtime(
                            default_cinema,
                            movie,
                            show_date,
                            start_time,
                            showtime_format=showtime_format,
                            language=language,
                        )
                    )

        if results:
            return self._dedupe(results)

        return self._dedupe(self._parse_lines(default_cinema, soup, movie_details or {}))

    def _parse_cinema_options(self, soup: BeautifulSoup) -> list[ScrapedCinema]:
        cinemas: list[ScrapedCinema] = []
        options = soup.select("#CinemaNameTWInfoF option")
        if not options:
            options = soup.select("#CinemaNameTWInfoS option")
        if not options:
            options = soup.select("select.LangTW option")
        for option in options:
            name = option.get_text(" ", strip=True)
            value = option.get("value")
            if not name or "請選擇" in name or "Please choose" in name:
                continue
            canonical_name = CINEMA_NAME_BY_CODE.get(value or "", name)
            detail_key = self._cinema_key(canonical_name)
            details = self.cinema_details.get(detail_key)
            fallback_address = CINEMA_ADDRESS_BY_CODE.get(value or "")
            address = (details.address if details else None) or fallback_address
            cinemas.append(
                ScrapedCinema(
                    chain=CHAIN,
                    name=canonical_name,
                    city=(details.city if details else None)
                    or self._city_from_address(address)
                    or self._guess_city(canonical_name),
                    address=address,
                    source_cinema_id=value,
                )
            )
        return cinemas

    def _extract_movie_keys_from_theater_detail_html(self, html: str) -> set[str]:
        soup = BeautifulSoup(html, "lxml")
        lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n", strip=True).splitlines()]
        lines = [line for line in lines if line]
        keys: set[str] = set()
        for index, line in enumerate(lines):
            if not self._looks_like_theater_movie_title(line):
                continue
            keys.add(self._movie_key(line))
            next_line = lines[index + 1] if index + 1 < len(lines) else None
            if next_line and self._looks_like_english_title(next_line):
                keys.add(self._movie_key(next_line))
        keys.discard("")
        return keys

    def _parse_theater_detail_showtimes(
        self,
        html: str,
        page_url: str,
        movie_details: dict[str, ScrapedMovie] | None = None,
    ) -> list[ScrapedShowtime]:
        soup = BeautifulSoup(html, "lxml")
        cinema = self._parse_theater_detail_cinema(soup, page_url)
        if not cinema:
            return []

        lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n", strip=True).splitlines()]
        lines = [line for line in lines if line]
        showtime_start = self._find_showtime_start(lines)
        if showtime_start is None:
            return []

        available_dates = self._dates_from_theater_detail_lines(lines[showtime_start:])
        if not available_dates:
            return []

        warning_indexes = [
            index
            for index in range(showtime_start, len(lines))
            if "網路訂票僅開放" in lines[index]
        ]
        if not warning_indexes:
            return []

        results: list[ScrapedShowtime] = []
        for group_index, start in enumerate(warning_indexes):
            if group_index >= len(available_dates):
                break
            end = warning_indexes[group_index + 1] if group_index + 1 < len(warning_indexes) else len(lines)
            group_lines = lines[start + 1 : end]
            results.extend(
                self._parse_theater_detail_showtime_group(
                    cinema=cinema,
                    show_date=available_dates[group_index],
                    lines=group_lines,
                    movie_details=movie_details or {},
                )
            )
        return self._dedupe(results)

    def _parse_theater_detail_cinema(self, soup: BeautifulSoup, page_url: str) -> ScrapedCinema | None:
        heading_text = None
        for selector in [".theaterTitle h1", ".theaterInfo h1", "h1", "h2"]:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if "威秀影城" in text or "MUVIE CINEMAS" in text:
                    heading_text = text
                    break

        if not heading_text:
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            match = re.search(r"威秀影城\s*-\s*(.+)", title)
            heading_text = match.group(1).strip() if match else None
        if not heading_text:
            return None

        name = re.split(r"\s{2,}| Vie Show Cinemas | MUVIE CINEMAS TAIPEI| MUVIE CINEMAS Taichung", heading_text)[0].strip()
        name = re.sub(r"\s+Vie Show Cinemas.*$", "", name).strip()
        address = self._address_from_theater_detail(soup)
        source_cinema_id = self._source_theater_id(page_url)
        return ScrapedCinema(
            chain=CHAIN,
            name=name,
            city=self._city_from_address(address) or self._guess_city(name),
            address=address,
            source_cinema_id=source_cinema_id,
        )

    def _address_from_theater_detail(self, soup: BeautifulSoup) -> str | None:
        lines = self._text_lines(soup)
        for index, line in enumerate(lines):
            normalized = line.replace(" ", "")
            if not normalized.startswith("影城地址"):
                continue
            value = re.sub(r"^影城地址\s*[：:]?\s*", "", line).strip()
            if value:
                return value
            address_parts: list[str] = []
            for next_line in lines[index + 1 : index + 4]:
                if "服務專線" in next_line or "交通資訊" in next_line:
                    break
                if next_line and next_line not in {"：", ":"}:
                    address_parts.append(next_line)
            return " ".join(address_parts).strip() or None
        return None

    def _source_theater_id(self, page_url: str) -> str | None:
        match = re.search(r"detail(?P<kind>2?)\.aspx\?id=(?P<id>\d+)", page_url)
        if not match:
            return None
        prefix = "detail2" if match.group("kind") == "2" else "detail"
        return f"{prefix}:{match.group('id')}"

    def _find_showtime_start(self, lines: list[str]) -> int | None:
        for index, line in enumerate(lines):
            if "場次查詢" in line:
                return index
        return None

    def _dates_from_theater_detail_lines(self, lines: list[str]) -> list[date]:
        dates: list[date] = []
        for line in lines:
            if "網路訂票僅開放" in line:
                break
            parsed = self._parse_tw_date(line)
            if parsed and parsed not in dates:
                dates.append(parsed)
        return dates

    def _parse_theater_detail_showtime_group(
        self,
        cinema: ScrapedCinema,
        show_date: date,
        lines: list[str],
        movie_details: dict[str, ScrapedMovie],
    ) -> list[ScrapedShowtime]:
        results: list[ScrapedShowtime] = []
        current_movie: ScrapedMovie | None = None
        current_format: str | None = None
        current_language: str | None = None
        index = 0
        while index < len(lines):
            line = lines[index]
            if self._is_theater_detail_stop_line(line):
                break

            if self._looks_like_version_label(line):
                parsed = self._split_version_label(line)
                current_format = parsed["format"]
                current_language = parsed["language"]
                index += 1
                continue

            time_matches = list(re.finditer(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", line))
            if time_matches and current_movie and current_format:
                for time_match in time_matches:
                    start_time = time(int(time_match.group("hour")), int(time_match.group("minute")))
                    results.append(
                        self._build_showtime(
                            cinema,
                            current_movie,
                            show_date,
                            start_time,
                            showtime_format=current_format,
                            language=current_language,
                        )
                    )
                index += 1
                continue

            if self._looks_like_theater_movie_title(line):
                title_zh = line
                title_en = None
                next_line = lines[index + 1] if index + 1 < len(lines) else None
                if next_line and self._looks_like_english_title(next_line):
                    title_en = next_line
                    index += 1
                current_movie = self._movie_from_theater_detail_titles(title_zh, title_en, movie_details)
                current_format = None
                current_language = None

            index += 1
        return self._dedupe(results)

    def _movie_from_theater_detail_titles(
        self,
        title_zh: str,
        title_en: str | None,
        movie_details: dict[str, ScrapedMovie],
    ) -> ScrapedMovie:
        detail = self._find_movie_detail(movie_details, title_zh, title_en)
        if not detail:
            return ScrapedMovie(
                title=title_zh,
                title_zh=title_zh,
                title_en=title_en,
                original_title=title_en,
            )
        return ScrapedMovie(
            title=title_zh or detail.title,
            title_zh=title_zh or detail.title_zh,
            title_en=title_en or detail.title_en,
            original_title=title_en or detail.original_title,
            poster_url=detail.poster_url,
            still_urls=detail.still_urls,
            release_date=detail.release_date,
            duration_minutes=detail.duration_minutes,
            rating=detail.rating,
            genre=detail.genre,
            description=detail.description,
            director=detail.director,
            cast=detail.cast,
            cast_photo_urls=detail.cast_photo_urls,
            trailer_url=detail.trailer_url,
            detail_url=detail.detail_url,
            source_movie_id=detail.source_movie_id,
        )

    def _is_theater_detail_stop_line(self, line: str) -> bool:
        return any(
            marker in line
            for marker in [
                "票價資訊",
                "影城活動",
                "影城資訊",
                "Copyright",
                "快速訂票",
                "請選擇影城",
            ]
        )

    def _looks_like_version_label(self, line: str) -> bool:
        if len(line) > 60:
            return False
        return bool(
            re.search(
                r"數位|IMAX|4DX|TITAN|MUCROWN|GOLD CLASS|GC|LIVE|ATMOS|Dolby|DOLBY",
                line,
                re.IGNORECASE,
            )
        )

    def _split_version_label(self, label: str) -> dict[str, str | None]:
        text = re.sub(r"\s+", " ", label).strip()
        language = self._language_from_prefixes([text])
        showtime_format = re.sub(r"\((英|國|日|韓|粵|多元語)\)", "", text).strip()
        return {
            "format": showtime_format or text,
            "language": language,
        }

    def _looks_like_theater_movie_title(self, line: str) -> bool:
        if not self._looks_like_movie_title(line):
            return False
        ignored = [
            "MORE",
            "LOADING",
            "首頁",
            "場次查詢",
            "售票公告",
            "入場須知",
            "隔日",
            "特別場",
            "口碑場",
            "粉絲場",
        ]
        if any(word in line for word in ignored):
            return False
        if re.fullmatch(r"[（(][^)）]+[)）]", line):
            return False
        return not self._looks_like_version_label(line)

    def _looks_like_english_title(self, line: str) -> bool:
        if len(line) < 2 or len(line) > 160:
            return False
        if self._looks_like_version_label(line):
            return False
        if re.search(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", line):
            return False
        return bool(re.search(r"[A-Za-z]", line))

    def _extract_title(self, text: str) -> str | None:
        # Placeholder heuristics. Tune after viewing debug/vieshow-showtimes.html.
        ignored = ["場次查詢", "Show Times", "請選擇", "Session Time"]
        if any(word in text for word in ignored):
            return None
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 2:
            return None
        return text[:120]

    def _extract_times_from_text(
        self,
        cinema: ScrapedCinema,
        movie: ScrapedMovie,
        text: str,
    ) -> list[ScrapedShowtime]:
        current_year = datetime.now().year
        found: list[ScrapedShowtime] = []

        # Matches date labels such as 05月13日, 05/13, then time labels such as 14:30.
        dates = list(re.finditer(r"(?P<month>\d{1,2})[月/](?P<day>\d{1,2})(?:日)?", text))
        times = list(re.finditer(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", text))

        if not times:
            return []

        if not dates:
            show_date = date.today()
            for match in times:
                start_time = time(int(match.group("hour")), int(match.group("minute")))
                found.append(self._build_showtime(cinema, movie, show_date, start_time))
            return found

        for i, date_match in enumerate(dates):
            month = int(date_match.group("month"))
            day = int(date_match.group("day"))
            try:
                show_date = date(current_year, month, day)
            except ValueError:
                continue

            start = date_match.end()
            end = dates[i + 1].start() if i + 1 < len(dates) else len(text)
            section = text[start:end]
            for time_match in re.finditer(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", section):
                start_time = time(int(time_match.group("hour")), int(time_match.group("minute")))
                found.append(self._build_showtime(cinema, movie, show_date, start_time))

        return found

    def _parse_lines(
        self,
        cinema: ScrapedCinema,
        soup: BeautifulSoup,
        movie_details: dict[str, ScrapedMovie] | None = None,
    ) -> list[ScrapedShowtime]:
        current_year = datetime.now().year
        current_date: date | None = None
        current_movie: ScrapedMovie | None = None
        found: list[ScrapedShowtime] = []

        text = soup.get_text("\n", strip=True)
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        for line in lines:
            if not line:
                continue

            date_match = re.search(r"(?P<month>\d{1,2})[月/](?P<day>\d{1,2})(?:日)?", line)
            if date_match:
                try:
                    current_date = date(
                        current_year,
                        int(date_match.group("month")),
                        int(date_match.group("day")),
                    )
                except ValueError:
                    current_date = None

            time_matches = list(re.finditer(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", line))
            if time_matches and current_movie:
                show_date = current_date or date.today()
                for time_match in time_matches:
                    start_time = time(
                        int(time_match.group("hour")),
                        int(time_match.group("minute")),
                    )
                    found.append(self._build_showtime(cinema, current_movie, show_date, start_time))
                continue

            if self._looks_like_movie_title(line):
                parsed = self._split_movie_label(line[:120])
                key = self._movie_key(parsed["title"])
                current_movie = self._find_movie_detail(movie_details or {}, parsed["title"]) or ScrapedMovie(
                    title=parsed["title"],
                    title_zh=parsed["title"],
                    rating=parsed["rating"],
                )

        return found

    def _looks_like_movie_title(self, line: str) -> bool:
        if len(line) < 2 or len(line) > 120:
            return False
        ignored = [
            "場次",
            "時間表",
            "請選擇",
            "影城",
            "Show Times",
            "Session",
            "Copyright",
            "中文",
            "English",
            "版本",
            "級",
            "廳",
            "座位",
            "售完",
            "訂票",
            "開放",
        ]
        if any(word in line for word in ignored):
            return False
        if re.search(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)", line):
            return False
        if re.search(r"\d{1,2}[月/]\d{1,2}", line):
            return False
        return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", line))

    def _build_showtime(
        self,
        cinema: ScrapedCinema,
        movie: ScrapedMovie,
        show_date: date,
        start_time: time,
        showtime_format: str | None = None,
        language: str | None = None,
    ) -> ScrapedShowtime:
        version = self._normalize_version(showtime_format, language)
        key = f"{cinema.name}|{movie.title}|{version['version_label']}|{show_date.isoformat()}|{start_time.isoformat()}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return ScrapedShowtime(
            cinema=cinema,
            movie=movie,
            show_date=show_date,
            start_time=start_time,
            hall_name=None,
            format=showtime_format,
            language=language,
            booking_url=SHOWTIMES_URL,
            source="vieshow",
            source_showtime_id=digest,
            version_label=version["version_label"],
            auditorium_brand=version["auditorium_brand"],
            projection_type=version["projection_type"],
            audio_language=version["audio_language"],
            subtitle_language=version["subtitle_language"],
            source_payload={"version_text": showtime_format, "language": language},
        )

    def _normalize_version(
        self,
        showtime_format: str | None,
        language: str | None,
    ) -> dict[str, str | None]:
        format_text = (showtime_format or "").strip()
        language_text = (language or "").strip()
        version_label = format_text
        if language_text and language_text not in format_text:
            short_language = self._short_language(language_text)
            version_label = f"{format_text}({short_language})" if format_text else short_language

        upper_format = format_text.upper()
        auditorium_brand = None
        for brand in ["MUCROWN", "TITAN", "IMAX", "4DX", "GOLD CLASS", "GC", "LIVE"]:
            if brand in upper_format:
                auditorium_brand = brand
                break

        projection_type = None
        if "3D" in upper_format:
            projection_type = "3D"
        elif "2D" in upper_format or "數位" in format_text:
            projection_type = "數位"

        return {
            "version_label": version_label or None,
            "auditorium_brand": auditorium_brand,
            "projection_type": projection_type,
            "audio_language": language_text or None,
            "subtitle_language": None,
        }

    def _short_language(self, language: str) -> str:
        mapping = {
            "英語": "英",
            "國語": "國",
            "日語": "日",
            "韓語": "韓",
            "粵語": "粵",
            "多元語": "多元語",
        }
        return mapping.get(language, language)

    def _movie_from_labels(
        self,
        tw_label: str,
        en_label: str | None,
        movie_details: dict[str, ScrapedMovie],
    ) -> tuple[ScrapedMovie, str | None, str | None]:
        tw = self._split_movie_label(tw_label)
        en = self._split_movie_label(en_label or "")
        detail = self._find_movie_detail(movie_details, tw["title"], en["title"])
        title_zh = tw["title"] or (detail.title_zh if detail else None) or (detail.title if detail else None)
        title_en = en["title"] or (detail.title_en if detail else None)
        rating = tw["rating"] or (detail.rating if detail else None)
        showtime_format = tw["format"] or en["format"]
        language = tw["language"]
        if detail:
            return (
                ScrapedMovie(
                    title=title_zh or detail.title,
                    title_zh=title_zh,
                    title_en=title_en,
                    original_title=title_en or detail.original_title,
                    poster_url=detail.poster_url,
                    still_urls=detail.still_urls,
                    release_date=detail.release_date,
                    duration_minutes=detail.duration_minutes,
                    rating=rating,
                    genre=detail.genre,
                    description=detail.description,
                    director=detail.director,
                    cast=detail.cast,
                    cast_photo_urls=detail.cast_photo_urls,
                    trailer_url=detail.trailer_url,
                    detail_url=detail.detail_url,
                    source_movie_id=detail.source_movie_id,
                ),
                showtime_format,
                language,
            )
        return (
            ScrapedMovie(
                title=title_zh or title_en or tw_label,
                title_zh=title_zh,
                title_en=title_en,
                original_title=title_en,
                rating=rating,
            ),
            showtime_format,
            language,
        )

    def _find_movie_detail(
        self,
        movie_details: dict[str, ScrapedMovie],
        *titles: str | None,
    ) -> ScrapedMovie | None:
        keys = [self._movie_key(title) for title in titles if title]
        for key in keys:
            detail = movie_details.get(key)
            if detail:
                return detail

        for key in keys:
            for detail_key, detail in movie_details.items():
                if self._movie_keys_match(detail_key, key):
                    return detail
        return None

    def _split_movie_label(self, label: str) -> dict[str, str | None]:
        text = re.sub(r"\s+", " ", label or "").strip()
        prefixes: list[str] = []
        while True:
            match = re.match(r"^\(([^)]+)\)\s*", text)
            if not match:
                break
            value = match.group(1).strip()
            if self._looks_like_rating(value):
                break
            prefixes.append(value)
            text = text[match.end() :].strip()

        rating = None
        match = re.search(r"\(([^)]+)\)\s*$", text)
        if match and self._looks_like_rating(match.group(1)):
            rating = self._normalize_rating(match.group(1))
            text = text[: match.start()].strip()

        language = self._language_from_prefixes(prefixes)
        showtime_format = " ".join(prefixes) if prefixes else None
        return {
            "title": text.strip(),
            "format": showtime_format,
            "language": language,
            "rating": rating,
        }

    def _looks_like_rating(self, value: str) -> bool:
        text = value.strip()
        if re.search(r"普遍級|保護級|輔12級|輔15級|限制級|待定", text):
            return True
        return text.upper() in {"G", "P", "PG", "TBC", "R"}

    def _normalize_rating(self, value: str) -> str:
        mapping = {
            "G": "普遍級",
            "P": "保護級",
            "PG": "輔導級",
            "TBC": "待定",
            "R": "限制級",
        }
        text = value.strip()
        return mapping.get(text.upper(), text)

    def _language_from_prefixes(self, prefixes: list[str]) -> str | None:
        joined = " ".join(prefixes)
        if "國" in joined:
            return "國語"
        if "英" in joined:
            return "英語"
        if "日" in joined:
            return "日語"
        if "韓" in joined:
            return "韓語"
        if "粵" in joined:
            return "粵語"
        if "多元語" in joined:
            return "多元語"
        return None

    def _parse_tw_date(self, text: str) -> date | None:
        match = re.search(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日", text)
        if not match:
            match = re.search(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})", text)
        if not match:
            return None
        try:
            return date(datetime.now().year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None

    def _movie_key(self, title: str | None) -> str:
        if not title:
            return ""
        text = self._split_movie_label(title)["title"] or title
        text = re.sub(r"[：:：－—\-・·\s　！!？?（）()《》「」『』,.，。/\\]+", "", text)
        return text.lower()

    def _text_lines(self, soup: BeautifulSoup) -> list[str]:
        return [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]

    def _first_heading_text(self, soup: BeautifulSoup, selectors: list[str]) -> str | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text and text not in {"MOVIE INFO", "劇情簡介ABOUT THE STORY"}:
                    return text
        return None

    def _field_from_lines(self, lines: list[str], label: str) -> str | None:
        field_labels = {"導演", "演員", "類型", "片長", "上映日期"}
        for index, line in enumerate(lines):
            compact = line.replace(" ", "")
            if compact.startswith(label):
                value = re.sub(rf"^{label}\s*[：:|]?\s*", "", line).strip(" |")
                if value:
                    return value
                for next_line in lines[index + 1 : index + 4]:
                    if any(next_line.replace(" ", "").startswith(field_label) for field_label in field_labels):
                        return None
                    value = next_line.strip(" |")
                    if value and value not in {"|", "：", ":"}:
                        return value
        text = "\n".join(lines)
        match = re.search(rf"{label}\s*[：:]\s*\|?\s*(.+)", text)
        return match.group(1).strip() if match else None

    def _field_from_detail_table(self, soup: BeautifulSoup, label: str) -> str | None:
        for row in soup.select(".infoArea table tr"):
            cells = row.select("td")
            if len(cells) < 2:
                continue
            key = cells[0].get_text(" ", strip=True).replace(" ", "")
            if not key.startswith(label):
                continue
            value = cells[1].get_text(" ", strip=True)
            return value or None
        return None

    def _description_from_dom(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one(".bbsArticle")
        if not node:
            return None
        return node.get_text("\n", strip=True) or None

    def _release_date_text(self, soup: BeautifulSoup) -> str | None:
        node = soup.select_one(".movieMain .titleArea time")
        if node:
            return node.get_text(" ", strip=True)
        return self._field_from_lines(self._text_lines(soup), "上映日期")

    def _description_from_lines(self, lines: list[str]) -> str | None:
        start = None
        for index, line in enumerate(lines):
            if "劇情簡介" in line or "ABOUT THE STORY" in line:
                start = index + 1
                break
        if start is None:
            return None
        stop_words = ["電影場次", "MOVIE TIME", "放映版本", "快速訂票"]
        content: list[str] = []
        for line in lines[start:]:
            if any(word in line for word in stop_words):
                break
            if line:
                content.append(line)
        return "\n".join(content).strip() or None

    def _extract_poster_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        img = soup.select_one(".movieMain figure img[src]")
        if img and img.get("src"):
            return urljoin(page_url, img["src"])
        return None

    def _extract_still_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        urls: list[str] = []
        for anchor in soup.select(".movieGallery a[href], #photoBox a[href]"):
            href = anchor.get("href")
            if href:
                urls.append(urljoin(page_url, href))
        for img in soup.select(".movieGallery img[src], #photoBox img[src]"):
            src = img.get("src")
            if src:
                urls.append(urljoin(page_url, src))
        return list(dict.fromkeys(urls))

    def _extract_image_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        urls: list[str] = []
        poster_url = self._extract_poster_url(soup, page_url)
        if poster_url:
            urls.append(poster_url)
        urls.extend(self._extract_still_urls(soup, page_url))
        return urls

    def _extract_trailer_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        for node in soup.select("iframe[src]"):
            url = node.get("src")
            if not url:
                continue
            full_url = urljoin(page_url, url)
            if "youtube.com" in full_url or "youtu.be" in full_url:
                return full_url
        for node in soup.select("a[href]"):
            url = node.get("src") or node.get("href")
            if not url:
                continue
            full_url = urljoin(page_url, url)
            if "youtube.com" in full_url or "youtu.be" in full_url:
                return full_url
        return None

    def _parse_duration(self, text: str | None) -> int | None:
        if not text:
            return None
        hour_match = re.search(r"(\d+)\s*時", text)
        minute_match = re.search(r"(\d+)\s*分", text)
        if hour_match or minute_match:
            hours = int(hour_match.group(1)) if hour_match else 0
            minutes = int(minute_match.group(1)) if minute_match else 0
            return hours * 60 + minutes
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None

    def _parse_release_date(self, text: str | None) -> date | None:
        if not text:
            return None
        match = re.search(r"(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})", text)
        if not match:
            return None
        try:
            return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None

    def _source_movie_id(self, detail_url: str) -> str | None:
        match = re.search(r"[?&]id=(\d+)", detail_url)
        return match.group(1) if match else None

    def _guess_city(self, cinema_name: str) -> str | None:
        for city in ["台北", "新北", "桃園", "新竹", "苗栗", "台中", "台南", "高雄", "花蓮"]:
            if city in cinema_name:
                return city
        if "板橋" in cinema_name or "中和" in cinema_name or "新店" in cinema_name or "林口" in cinema_name:
            return "新北"
        if "頭份" in cinema_name:
            return "苗栗"
        return None

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
            "花蓮縣": "花蓮",
        }
        for prefix, city in city_aliases.items():
            if prefix in address:
                return city
        return None

    def _cinema_key(self, name: str | None) -> str:
        if not name:
            return ""
        return re.sub(r"[\s　()（）]+", "", name).lower()

    def _dedupe(self, items: list[ScrapedShowtime]) -> list[ScrapedShowtime]:
        seen: set[str] = set()
        output: list[ScrapedShowtime] = []
        for item in items:
            if item.source_showtime_id in seen:
                continue
            seen.add(item.source_showtime_id)
            output.append(item)
        return output
