import time
from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.scrapers.ambassador import AmbassadorScraper
from app.scrapers.eslite import EsliteScraper
from app.scrapers.halarcity import HalarCityScraper
from app.scrapers.in89 import In89Scraper
from app.scrapers.kfa import KfaScraper
from app.scrapers.miramar import MiramarScraper
from app.scrapers.miranew import MiranewScraper
from app.scrapers.skcinemas import SKCinemasScraper
from app.scrapers.spot import SpotScraper
from app.scrapers.spot_hs import SpotHuashanScraper
from app.scrapers.showtime_cinemas import ShowtimeCinemasScraper
from app.scrapers.vieshow import VieShowScraper
from app.services.importer import import_showtimes


def sync_vieshow():
    scraper = VieShowScraper(headless=True)
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[vieshow] imported {imported} showtimes")


def sync_showtimes():
    scraper = ShowtimeCinemasScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[showtimes] imported {imported} showtimes")


def sync_in89():
    scraper = In89Scraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[in89] imported {imported} showtimes")


def sync_ambassador():
    scraper = AmbassadorScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[ambassador] imported {imported} showtimes")


def sync_eslite():
    scraper = EsliteScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[eslite] imported {imported} showtimes")


def sync_halarcity():
    scraper = HalarCityScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[halarcity] imported {imported} showtimes")


def sync_kfa():
    scraper = KfaScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[kfa] imported {imported} showtimes")


def sync_miramar():
    scraper = MiramarScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[miramar] imported {imported} showtimes")


def sync_miranew():
    scraper = MiranewScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[miranew] imported {imported} showtimes")


def sync_skcinemas():
    scraper = SKCinemasScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[skcinemas] imported {imported} showtimes")


def sync_spot():
    scraper = SpotScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[spot] imported {imported} showtimes")


def sync_spot_hs():
    scraper = SpotHuashanScraper()
    items = scraper.scrape()
    with SessionLocal() as db:
        imported = import_showtimes(db, items)
    print(f"[spot_hs] imported {imported} showtimes")


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(sync_vieshow, "cron", hour="9,12,18,22", minute=5)
    scheduler.add_job(sync_showtimes, "cron", hour="9,12,18,22", minute=15)
    scheduler.add_job(sync_in89, "cron", hour="9,12,18,22", minute=25)
    scheduler.add_job(sync_ambassador, "cron", hour="9,12,18,22", minute=35)
    scheduler.add_job(sync_eslite, "cron", hour="9,12,18,22", minute=40)
    scheduler.add_job(sync_halarcity, "cron", hour="9,12,18,22", minute=42)
    scheduler.add_job(sync_kfa, "cron", hour="9,12,18,22", minute=45)
    scheduler.add_job(sync_miramar, "cron", hour="9,12,18,22", minute=50)
    scheduler.add_job(sync_miranew, "cron", hour="9,12,18,22", minute=55)
    scheduler.add_job(sync_skcinemas, "cron", hour="10,13,19,23", minute=5)
    scheduler.add_job(sync_spot, "cron", hour="10,13,19,23", minute=15)
    scheduler.add_job(sync_spot_hs, "cron", hour="10,13,19,23", minute=25)
    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
