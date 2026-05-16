import time

import typer

from app.db.session import SessionLocal
from app.scrapers.ambassador import AmbassadorScraper
from app.scrapers.breezecinemas import BreezeCinemasScraper
from app.scrapers.eslite import EsliteScraper
from app.scrapers.governor import GovernorScraper
from app.scrapers.halarcity import HalarCityScraper
from app.scrapers.in89 import In89Scraper
from app.scrapers.kfa import KfaScraper
from app.scrapers.luxcinema import LuxCinemaScraper
from app.scrapers.miramar import MiramarScraper
from app.scrapers.miranew import MiranewScraper
from app.scrapers.skcinemas import SKCinemasScraper
from app.scrapers.spot import SpotScraper
from app.scrapers.spot_hs import SpotHuashanScraper
from app.scrapers.showtime_cinemas import ShowtimeCinemasScraper
from app.scrapers.vieshow import VieShowScraper
from app.services.importer import replace_showtimes

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
def showtimes():
    scraper = ShowtimeCinemasScraper()
    _sync_source("showtimes", scraper, "Showtime Cinemas")


@app.command()
def in89():
    scraper = In89Scraper()
    _sync_source("in89", scraper, "in89 Cinemax")


@app.command()
def ambassador():
    scraper = AmbassadorScraper()
    _sync_source("ambassador", scraper, "Ambassador Theatres")


@app.command()
def breezecinemas():
    scraper = BreezeCinemasScraper()
    _sync_source("breezecinemas", scraper, "Breeze Cinemas")


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
def miramar():
    scraper = MiramarScraper()
    _sync_source("miramar", scraper, "Miramar Cinemas")


@app.command()
def miranew():
    scraper = MiranewScraper()
    _sync_source("miranew", scraper, "Miranew Cinemas")


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


@app.command("all")
def scrape_all(
    headless: bool = True,
    continue_on_error: bool = True,
    vieshow_retries: int = 1,
    vieshow_retry_delay_minutes: int = 15,
):
    scrapers = [
        ("showtimes", ShowtimeCinemasScraper(), "Showtime Cinemas"),
        ("in89", In89Scraper(), "in89 Cinemax"),
        ("ambassador", AmbassadorScraper(), "Ambassador Theatres"),
        ("breezecinemas", BreezeCinemasScraper(), "Breeze Cinemas"),
        ("eslite", EsliteScraper(), "Eslite Art House"),
        ("halarcity", HalarCityScraper(), "Halar Cinemas"),
        ("governor", GovernorScraper(), "Governor Cinemas"),
        ("kfa", KfaScraper(), "Kaohsiung Film Archive"),
        ("luxcinema", LuxCinemaScraper(), "LUX Cinema"),
        ("miramar", MiramarScraper(), "Miramar Cinemas"),
        ("miranew", MiranewScraper(), "Miranew Cinemas"),
        ("skcinemas", SKCinemasScraper(), "Shin Kong Cinemas"),
        ("spot", SpotScraper(), "SPOT Taipei"),
        ("spot_hs", SpotHuashanScraper(), "SPOT Huashan"),
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
    if failures:
        typer.echo(
            "Failed sources: " + ", ".join(source for source, _ in failures),
            err=True,
        )
        raise typer.Exit(code=1 if not continue_on_error else 0)


if __name__ == "__main__":
    app()
