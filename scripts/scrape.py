import time
import os

from dotenv import load_dotenv
import typer

from app.db.session import SessionLocal
from app.scrapers.acecinema import AceCinemaScraper
from app.scrapers.ambassador import AmbassadorScraper
from app.scrapers.broadway import BroadwayScraper
from app.scrapers.breezecinemas import BreezeCinemasScraper
from app.scrapers.carnival import CarnivalScraper
from app.scrapers.ccmovie import CcMovieScraper
from app.scrapers.cm_movie import CmMovieScraper
from app.scrapers.eslite import EsliteScraper
from app.scrapers.governor import GovernorScraper
from app.scrapers.halarcity import HalarCityScraper
from app.scrapers.ilanmovie import IlanMovieScraper
from app.scrapers.in89 import In89Scraper
from app.scrapers.kfa import KfaScraper
from app.scrapers.luxcinema import LuxCinemaScraper
from app.scrapers.lunacinemax import LunaCinemaxScraper
from app.scrapers.madou import MadouScraper
from app.scrapers.machi import MachiCinemaScraper
from app.scrapers.miramar import MiramarScraper
from app.scrapers.miranew import MiranewScraper
from app.scrapers.mldcinema import MLDCinemaScraper
from app.scrapers.nantai import NantaiScraper
from app.scrapers.nantou import NantouTheaterScraper
from app.scrapers.opentix import OpenTixScraper
from app.scrapers.sbc import SbcScraper
from app.scrapers.shanming import ShanmingScraper
from app.scrapers.skcinemas import SKCinemasScraper
from app.scrapers.spot import SpotScraper
from app.scrapers.spot_hs import SpotHuashanScraper
from app.scrapers.showtime_cinemas import ShowtimeCinemasScraper
from app.scrapers.srm import SrmScraper
from app.scrapers.timescinema import TimesCinemaScraper
from app.scrapers.tmovies import TMoviesScraper
from app.scrapers.ucc import UccScraper
from app.scrapers.uch import UchScraper
from app.scrapers.venice import VeniceScraper
from app.scrapers.vieshow import VieShowScraper
from app.scrapers.wonderful import WonderfulScraper
from app.services.importer import ensure_schema, replace_showtimes
from app.utils.youtube_api import YouTubeApiClient, YouTubeApiError
from app.utils.youtube_web import YouTubeWebSearchClient, YouTubeWebSearchError
from enrich_trailers import (
    apply_updates,
    find_trailer_updates,
    find_youtube_trailer_updates,
    find_youtube_web_trailer_updates,
)

app = typer.Typer()


def _sync_source(source: str, scraper, label: str) -> int:
    items = scraper.scrape()
    typer.echo(f"[{source}] Scraped {len(items)} showtimes from {label}")
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source=source)
    typer.echo(f"[{source}] Imported {imported} showtimes")
    return imported


def _sync_source_with_retry(
    source: str,
    scraper_factory,
    label: str,
    retries: int = 1,
    retry_delay_minutes: int = 15,
) -> int:
    for attempt in range(1, retries + 2):
        try:
            return _sync_source(source, scraper_factory(), label)
        except Exception as exc:
            if attempt > retries:
                raise
            typer.echo(
                f"[{source}] Failed attempt {attempt}/{retries + 1}: {exc}",
                err=True,
            )
            typer.echo(
                f"[{source}] Retrying in {retry_delay_minutes} minutes...",
                err=True,
            )
            time.sleep(retry_delay_minutes * 60)
    raise RuntimeError(f"{source} retry loop exited unexpectedly")


def _sync_trailer_video_ids(
    youtube_web: bool = True,
    youtube_api: bool = False,
    youtube_api_key: str | None = None,
    youtube_limit: int | None = None,
    youtube_min_score: int = 7,
    youtube_max_results: int = 5,
) -> int:
    load_dotenv()
    with SessionLocal() as db:
        ensure_schema(db)
        updates = find_trailer_updates(db)

        if youtube_api:
            api_key = youtube_api_key or os.getenv("YOUTUBE_API_KEY")
            if not api_key:
                raise RuntimeError("Missing YouTube API key. Set YOUTUBE_API_KEY or pass --youtube-api-key.")
            updates.extend(
                find_youtube_trailer_updates(
                    db,
                    YouTubeApiClient(api_key),
                    existing_updates=updates,
                    limit=youtube_limit,
                    min_score=youtube_min_score,
                    max_results=youtube_max_results,
                )
            )

        if youtube_web:
            updates.extend(
                find_youtube_web_trailer_updates(
                    db,
                    YouTubeWebSearchClient(),
                    existing_updates=updates,
                    limit=youtube_limit,
                )
            )

        if not updates:
            typer.echo("[trailers] No trailer updates found")
            return 0

        apply_updates(db, updates)
        db.commit()
        typer.echo(f"[trailers] Updated {len(updates)} movie trailers")
        return len(updates)


@app.command()
def vieshow(headless: bool = True, retries: int = 1, retry_delay_minutes: int = 15):
    _sync_source_with_retry(
        "vieshow",
        lambda: VieShowScraper(headless=headless),
        "Vie Show",
        retries=retries,
        retry_delay_minutes=retry_delay_minutes,
    )


@app.command()
def acecinema():
    scraper = AceCinemaScraper()
    _sync_source("acecinema", scraper, "ACE Cinemas")


@app.command()
def ccmovie():
    scraper = CcMovieScraper()
    _sync_source("ccmovie", scraper, "Chin Chin Cinema")


@app.command()
def carnival():
    scraper = CarnivalScraper()
    _sync_source("carnival", scraper, "Carnival Cinemas")


@app.command("cm-movie")
def cm_movie():
    scraper = CmMovieScraper()
    _sync_source("cm_movie", scraper, "今日全美戲院")


@app.command()
def showtimes():
    scraper = ShowtimeCinemasScraper()
    _sync_source("showtimes", scraper, "Showtime Cinemas")


@app.command()
def in89():
    scraper = In89Scraper()
    _sync_source("in89", scraper, "in89 Cinemax")


@app.command()
def ilanmovie():
    scraper = IlanMovieScraper()
    _sync_source("ilanmovie", scraper, "Ilan Movie")


@app.command()
def ambassador():
    scraper = AmbassadorScraper()
    _sync_source("ambassador", scraper, "Ambassador Theatres")


@app.command()
def breezecinemas():
    scraper = BreezeCinemasScraper()
    _sync_source("breezecinemas", scraper, "Breeze Cinemas")


@app.command()
def broadway():
    scraper = BroadwayScraper()
    _sync_source("broadway", scraper, "Broadway Cinemas")


@app.command()
def wonderful():
    scraper = WonderfulScraper()
    _sync_source("wonderful", scraper, "Wonderful Theatre")


@app.command()
def eslite():
    scraper = EsliteScraper()
    _sync_source("eslite", scraper, "Eslite Art House")


@app.command()
def halarcity():
    scraper = HalarCityScraper()
    _sync_source("halarcity", scraper, "Halar Cinemas")


@app.command()
def governor():
    scraper = GovernorScraper()
    _sync_source("governor", scraper, "Governor Cinemas")


@app.command()
def kfa():
    scraper = KfaScraper()
    _sync_source("kfa", scraper, "Kaohsiung Film Archive")


@app.command()
def luxcinema():
    scraper = LuxCinemaScraper()
    _sync_source("luxcinema", scraper, "LUX Cinema")


@app.command()
def lunacinemax():
    scraper = LunaCinemaxScraper()
    _sync_source("lunacinemax", scraper, "Luna Cinemax")


@app.command()
def madou():
    scraper = MadouScraper()
    _sync_source("madou", scraper, "麻豆戲院")


@app.command()
def machi():
    scraper = MachiCinemaScraper()
    _sync_source("machi", scraper, "Machi Cinema")


@app.command()
def miramar():
    scraper = MiramarScraper()
    _sync_source("miramar", scraper, "Miramar Cinemas")


@app.command()
def miranew():
    scraper = MiranewScraper()
    _sync_source("miranew", scraper, "Miranew Cinemas")


@app.command()
def mldcinema():
    scraper = MLDCinemaScraper()
    _sync_source("mldcinema", scraper, "MLD Cinema")


@app.command()
def nantai():
    scraper = NantaiScraper()
    _sync_source("nantai", scraper, "Nantai Cinema")


@app.command()
def opentix():
    scraper = OpenTixScraper()
    _sync_source("opentix", scraper, "OpenTIX")


@app.command()
def sbc():
    scraper = SbcScraper()
    _sync_source("sbc", scraper, "SBC Cinema")


@app.command()
def skcinemas():
    scraper = SKCinemasScraper()
    _sync_source("skcinemas", scraper, "Shin Kong Cinemas")


@app.command()
def spot():
    scraper = SpotScraper()
    _sync_source("spot", scraper, "SPOT Taipei")


@app.command("spot-hs")
def spot_hs():
    scraper = SpotHuashanScraper()
    _sync_source("spot_hs", scraper, "SPOT Huashan")


@app.command()
def srm():
    scraper = SrmScraper()
    _sync_source("srm", scraper, "Sunrise Movie")


@app.command()
def timescinema():
    scraper = TimesCinemaScraper()
    _sync_source("timescinema", scraper, "Times Cinema")


@app.command()
def tmovies():
    scraper = TMoviesScraper()
    _sync_source("tmovies", scraper, "T-Movies Cinema")


@app.command()
def ucc():
    scraper = UccScraper()
    _sync_source("ucc", scraper, "UCC Cinema")


@app.command()
def venice():
    scraper = VeniceScraper()
    _sync_source("venice", scraper, "Venice Cinemas")


@app.command()
def nantou():
    scraper = NantouTheaterScraper()
    _sync_source("nantou", scraper, "Nantou Theater")


@app.command()
def shanming():
    scraper = ShanmingScraper()
    _sync_source("shanming", scraper, "Shanming Cinema")


@app.command()
def uch():
    scraper = UchScraper()
    _sync_source("uch", scraper, "Universal Chunghwa Cinemas")


@app.command("all")
def scrape_all(
    headless: bool = True,
    continue_on_error: bool = True,
    vieshow_retries: int = 1,
    vieshow_retry_delay_minutes: int = 15,
    enrich_trailers: bool = True,
    youtube_web: bool = True,
    youtube_api: bool = False,
    youtube_api_key: str | None = None,
    youtube_limit: int | None = None,
    youtube_min_score: int = 7,
    youtube_max_results: int = 5,
):
    scrapers = [
        ("acecinema", AceCinemaScraper(), "ACE Cinemas"),
        ("ccmovie", CcMovieScraper(), "Chin Chin Cinema"),
        ("carnival", CarnivalScraper(), "Carnival Cinemas"),
        ("cm_movie", CmMovieScraper(), "今日全美戲院"),
        ("showtimes", ShowtimeCinemasScraper(), "Showtime Cinemas"),
        ("in89", In89Scraper(), "in89 Cinemax"),
        ("ilanmovie", IlanMovieScraper(), "Ilan Movie"),
        ("ambassador", AmbassadorScraper(), "Ambassador Theatres"),
        ("breezecinemas", BreezeCinemasScraper(), "Breeze Cinemas"),
        ("broadway", BroadwayScraper(), "Broadway Cinemas"),
        ("wonderful", WonderfulScraper(), "Wonderful Theatre"),
        ("eslite", EsliteScraper(), "Eslite Art House"),
        ("halarcity", HalarCityScraper(), "Halar Cinemas"),
        ("governor", GovernorScraper(), "Governor Cinemas"),
        ("kfa", KfaScraper(), "Kaohsiung Film Archive"),
        ("luxcinema", LuxCinemaScraper(), "LUX Cinema"),
        ("lunacinemax", LunaCinemaxScraper(), "Luna Cinemax"),
        ("madou", MadouScraper(), "麻豆戲院"),
        ("machi", MachiCinemaScraper(), "Machi Cinema"),
        ("miramar", MiramarScraper(), "Miramar Cinemas"),
        ("miranew", MiranewScraper(), "Miranew Cinemas"),
        ("mldcinema", MLDCinemaScraper(), "MLD Cinema"),
        ("nantai", NantaiScraper(), "Nantai Cinema"),
        ("opentix", OpenTixScraper(), "OpenTIX"),
        ("sbc", SbcScraper(), "SBC Cinema"),
        ("skcinemas", SKCinemasScraper(), "Shin Kong Cinemas"),
        ("spot", SpotScraper(), "SPOT Taipei"),
        ("spot_hs", SpotHuashanScraper(), "SPOT Huashan"),
        ("srm", SrmScraper(), "Sunrise Movie"),
        ("timescinema", TimesCinemaScraper(), "Times Cinema"),
        ("tmovies", TMoviesScraper(), "T-Movies Cinema"),
        ("ucc", UccScraper(), "UCC Cinema"),
        ("venice", VeniceScraper(), "Venice Cinemas"),
        ("nantou", NantouTheaterScraper(), "Nantou Theater"),
        ("shanming", ShanmingScraper(), "Shanming Cinema"),
        ("uch", UchScraper(), "Universal Chunghwa Cinemas"),
        ("vieshow", lambda: VieShowScraper(headless=headless), "Vie Show"),
    ]

    total = 0
    failures = []
    for source, scraper, label in scrapers:
        try:
            if source == "vieshow":
                total += _sync_source_with_retry(
                    source,
                    scraper,
                    label,
                    retries=vieshow_retries,
                    retry_delay_minutes=vieshow_retry_delay_minutes,
                )
            else:
                total += _sync_source(source, scraper, label)
        except Exception as exc:
            failures.append((source, exc))
            typer.echo(f"[{source}] Failed: {exc}", err=True)
            if not continue_on_error:
                raise

    typer.echo(f"Imported {total} showtimes from {len(scrapers) - len(failures)}/{len(scrapers)} sources")
    trailer_updates = 0
    if enrich_trailers:
        try:
            trailer_updates = _sync_trailer_video_ids(
                youtube_web=youtube_web,
                youtube_api=youtube_api,
                youtube_api_key=youtube_api_key,
                youtube_limit=youtube_limit,
                youtube_min_score=youtube_min_score,
                youtube_max_results=youtube_max_results,
            )
        except (YouTubeApiError, YouTubeWebSearchError, RuntimeError) as exc:
            failures.append(("trailers", exc))
            typer.echo(f"[trailers] Failed: {exc}", err=True)
            if not continue_on_error:
                raise

    if failures:
        typer.echo(
            "Failed sources: " + ", ".join(source for source, _ in failures),
            err=True,
        )
        raise typer.Exit(code=1 if not continue_on_error else 0)
    if enrich_trailers:
        typer.echo(f"Updated trailer_video_id for {trailer_updates} movie(s)")


if __name__ == "__main__":
    app()
