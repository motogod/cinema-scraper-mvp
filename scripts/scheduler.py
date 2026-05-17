import time
from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.scrapers.acecinema import AceCinemaScraper
from app.scrapers.ambassador import AmbassadorScraper
from app.scrapers.broadway import BroadwayScraper
from app.scrapers.breezecinemas import BreezeCinemasScraper
from app.scrapers.ccmovie import CcMovieScraper
from app.scrapers.eslite import EsliteScraper
from app.scrapers.governor import GovernorScraper
from app.scrapers.halarcity import HalarCityScraper
from app.scrapers.ilanmovie import IlanMovieScraper
from app.scrapers.in89 import In89Scraper
from app.scrapers.kfa import KfaScraper
from app.scrapers.luxcinema import LuxCinemaScraper
from app.scrapers.lunacinemax import LunaCinemaxScraper
from app.scrapers.machi import MachiCinemaScraper
from app.scrapers.miramar import MiramarScraper
from app.scrapers.miranew import MiranewScraper
from app.scrapers.opentix import OpenTixScraper
from app.scrapers.sbc import SbcScraper
from app.scrapers.skcinemas import SKCinemasScraper
from app.scrapers.spot import SpotScraper
from app.scrapers.spot_hs import SpotHuashanScraper
from app.scrapers.showtime_cinemas import ShowtimeCinemasScraper
from app.scrapers.srm import SrmScraper
from app.scrapers.timescinema import TimesCinemaScraper
from app.scrapers.tmovies import TMoviesScraper
from app.scrapers.venice import VeniceScraper
from app.scrapers.vieshow import VieShowScraper
from app.scrapers.wonderful import WonderfulScraper
from app.services.importer import replace_showtimes

VIESHOW_RETRIES = 1
VIESHOW_RETRY_DELAY_MINUTES = 15


def sync_vieshow():
    for attempt in range(1, VIESHOW_RETRIES + 2):
        try:
            scraper = VieShowScraper(headless=True)
            items = scraper.scrape()
            with SessionLocal() as db:
                imported = replace_showtimes(db, items, source="vieshow")
            print(f"[vieshow] imported {imported} showtimes")
            return
        except Exception as exc:
            if attempt > VIESHOW_RETRIES:
                raise
            print(
                f"[vieshow] failed attempt {attempt}/{VIESHOW_RETRIES + 1}: {exc}"
            )
            print(f"[vieshow] retrying in {VIESHOW_RETRY_DELAY_MINUTES} minutes")
            time.sleep(VIESHOW_RETRY_DELAY_MINUTES * 60)


def sync_acecinema():
    scraper = AceCinemaScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="acecinema")
    print(f"[acecinema] imported {imported} showtimes")


def sync_ccmovie():
    scraper = CcMovieScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="ccmovie")
    print(f"[ccmovie] imported {imported} showtimes")


def sync_showtimes():
    scraper = ShowtimeCinemasScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="showtimes")
    print(f"[showtimes] imported {imported} showtimes")


def sync_in89():
    scraper = In89Scraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="in89")
    print(f"[in89] imported {imported} showtimes")


def sync_ilanmovie():
    scraper = IlanMovieScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="ilanmovie")
    print(f"[ilanmovie] imported {imported} showtimes")


def sync_ambassador():
    scraper = AmbassadorScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="ambassador")
    print(f"[ambassador] imported {imported} showtimes")


def sync_breezecinemas():
    scraper = BreezeCinemasScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="breezecinemas")
    print(f"[breezecinemas] imported {imported} showtimes")


def sync_broadway():
    scraper = BroadwayScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="broadway")
    print(f"[broadway] imported {imported} showtimes")


def sync_wonderful():
    scraper = WonderfulScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="wonderful")
    print(f"[wonderful] imported {imported} showtimes")


def sync_eslite():
    scraper = EsliteScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="eslite")
    print(f"[eslite] imported {imported} showtimes")


def sync_halarcity():
    scraper = HalarCityScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="halarcity")
    print(f"[halarcity] imported {imported} showtimes")


def sync_governor():
    scraper = GovernorScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="governor")
    print(f"[governor] imported {imported} showtimes")


def sync_kfa():
    scraper = KfaScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="kfa")
    print(f"[kfa] imported {imported} showtimes")


def sync_luxcinema():
    scraper = LuxCinemaScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="luxcinema")
    print(f"[luxcinema] imported {imported} showtimes")


def sync_lunacinemax():
    scraper = LunaCinemaxScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="lunacinemax")
    print(f"[lunacinemax] imported {imported} showtimes")


def sync_machi():
    scraper = MachiCinemaScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="machi")
    print(f"[machi] imported {imported} showtimes")


def sync_miramar():
    scraper = MiramarScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="miramar")
    print(f"[miramar] imported {imported} showtimes")


def sync_miranew():
    scraper = MiranewScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="miranew")
    print(f"[miranew] imported {imported} showtimes")


def sync_opentix():
    scraper = OpenTixScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="opentix")
    print(f"[opentix] imported {imported} showtimes")


def sync_sbc():
    scraper = SbcScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="sbc")
    print(f"[sbc] imported {imported} showtimes")


def sync_skcinemas():
    scraper = SKCinemasScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="skcinemas")
    print(f"[skcinemas] imported {imported} showtimes")


def sync_spot():
    scraper = SpotScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="spot")
    print(f"[spot] imported {imported} showtimes")


def sync_spot_hs():
    scraper = SpotHuashanScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="spot_hs")
    print(f"[spot_hs] imported {imported} showtimes")


def sync_srm():
    scraper = SrmScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="srm")
    print(f"[srm] imported {imported} showtimes")


def sync_timescinema():
    scraper = TimesCinemaScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="timescinema")
    print(f"[timescinema] imported {imported} showtimes")


def sync_tmovies():
    scraper = TMoviesScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="tmovies")
    print(f"[tmovies] imported {imported} showtimes")


def sync_venice():
    scraper = VeniceScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = replace_showtimes(db, items, source="venice")
    print(f"[venice] imported {imported} showtimes")


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(sync_vieshow, "cron", hour="9,12,18,22", minute=5)
    scheduler.add_job(sync_acecinema, "cron", hour="9,12,18,22", minute=12)
    scheduler.add_job(sync_ccmovie, "cron", hour="9,12,18,22", minute=13)
    scheduler.add_job(sync_showtimes, "cron", hour="9,12,18,22", minute=15)
    scheduler.add_job(sync_in89, "cron", hour="9,12,18,22", minute=25)
    scheduler.add_job(sync_ilanmovie, "cron", hour="9,12,18,22", minute=27)
    scheduler.add_job(sync_ambassador, "cron", hour="9,12,18,22", minute=35)
    scheduler.add_job(sync_breezecinemas, "cron", hour="9,12,18,22", minute=38)
    scheduler.add_job(sync_broadway, "cron", hour="9,12,18,22", minute=41)
    scheduler.add_job(sync_wonderful, "cron", hour="9,12,18,22", minute=39)
    scheduler.add_job(sync_eslite, "cron", hour="9,12,18,22", minute=40)
    scheduler.add_job(sync_halarcity, "cron", hour="9,12,18,22", minute=42)
    scheduler.add_job(sync_governor, "cron", hour="9,12,18,22", minute=43)
    scheduler.add_job(sync_kfa, "cron", hour="9,12,18,22", minute=45)
    scheduler.add_job(sync_luxcinema, "cron", hour="9,12,18,22", minute=48)
    scheduler.add_job(sync_lunacinemax, "cron", hour="9,12,18,22", minute=47)
    scheduler.add_job(sync_machi, "cron", hour="9,12,18,22", minute=49)
    scheduler.add_job(sync_miramar, "cron", hour="9,12,18,22", minute=50)
    scheduler.add_job(sync_miranew, "cron", hour="9,12,18,22", minute=55)
    scheduler.add_job(sync_opentix, "cron", hour="10,13,19,23", minute=0)
    scheduler.add_job(sync_sbc, "cron", hour="10,13,19,23", minute=2)
    scheduler.add_job(sync_skcinemas, "cron", hour="10,13,19,23", minute=5)
    scheduler.add_job(sync_spot, "cron", hour="10,13,19,23", minute=15)
    scheduler.add_job(sync_spot_hs, "cron", hour="10,13,19,23", minute=25)
    scheduler.add_job(sync_srm, "cron", hour="10,13,19,23", minute=30)
    scheduler.add_job(sync_timescinema, "cron", hour="10,13,19,23", minute=32)
    scheduler.add_job(sync_tmovies, "cron", hour="10,13,19,23", minute=35)
    scheduler.add_job(sync_venice, "cron", hour="10,13,19,23", minute=45)
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
