from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True)
class ScrapedCinema:
    chain: str
    name: str
    city: str | None = None
    address: str | None = None
    source_cinema_id: str | None = None


@dataclass(frozen=True)
class ScrapedMovie:
    title: str
    title_zh: str | None = None
    title_en: str | None = None
    original_title: str | None = None
    poster_url: str | None = None
    still_urls: list[str] | None = None
    release_date: date | None = None
    duration_minutes: int | None = None
    rating: str | None = None
    genre: str | None = None
    description: str | None = None
    director: str | None = None
    cast: str | None = None
    cast_photo_urls: list[str] | None = None
    trailer_url: str | None = None
    detail_url: str | None = None
    source_movie_id: str | None = None


@dataclass(frozen=True)
class ScrapedShowtime:
    cinema: ScrapedCinema
    movie: ScrapedMovie
    show_date: date
    start_time: time
    hall_name: str | None
    format: str | None
    language: str | None
    booking_url: str | None
    source: str
    source_showtime_id: str
    version_label: str | None = None
    auditorium_brand: str | None = None
    projection_type: str | None = None
    audio_language: str | None = None
    subtitle_language: str | None = None
    source_payload: dict | None = None
