from datetime import date, time
from pydantic import BaseModel, ConfigDict, Field


class CinemaChainOut(BaseModel):
    id: int
    code: str
    name: str
    website_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CinemaOut(BaseModel):
    id: int
    chain_id: int | None = None
    chain: str
    name: str
    city: str | None = None
    address: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MovieSourceOut(BaseModel):
    id: int
    source: str
    source_movie_id: str
    source_title: str | None = None
    source_original_title: str | None = None
    detail_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MovieOut(BaseModel):
    id: int
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
    trailer_video_id: str | None = None
    youtube_thumbnail: str | None = None
    detail_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MovieListOut(BaseModel):
    id: int | None = None
    movie_id: int | None = None
    title: str
    title_en: str | None = None
    poster_url: str | None = None
    youtube_thumbnail: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MovieDetailOut(MovieOut):
    sources: list[MovieSourceOut] = Field(default_factory=list)


class ShowtimeOut(BaseModel):
    id: int
    show_date: date
    start_time: time
    hall_name: str | None = None
    format: str | None = None
    language: str | None = None
    version_label: str | None = None
    auditorium_brand: str | None = None
    projection_type: str | None = None
    audio_language: str | None = None
    subtitle_language: str | None = None
    booking_url: str | None = None
    source_payload: dict | None = None
    source: str
    cinema: CinemaOut
    movie: MovieOut

    model_config = ConfigDict(from_attributes=True)


class MovieSessionOut(BaseModel):
    time: str
    show_date: date | None = None
    start_time: time | None = None
    format: str | None = None
    language: str | None = None
    version_label: str | None = None
    auditorium_brand: str | None = None
    projection_type: str | None = None
    audio_language: str | None = None
    subtitle_language: str | None = None
    hall_name: str | None = None
    booking_url: str | None = None


class MovieWithShowtimesOut(MovieOut):
    showtimes: list[str]
    sessions: list[MovieSessionOut] = Field(default_factory=list)


class GroupedShowtimesOut(BaseModel):
    cinema: CinemaOut
    show_date: date
    movies: list[MovieWithShowtimesOut]


class GroupedShowtimeMovieOut(BaseModel):
    id: int
    title: str
    original_title: str | None = None
    poster_url: str | None = None
    rating: str | None = None
    genre: str | None = None
    format: str | None = None
    start_time: list[str]


class MovieSearchOut(BaseModel):
    movie_id: int
    title: str
    title_en: str | None = None
    poster_url: str | None = None
    genre: str | None = None
    rating: str | None = None
    duration_minutes: int | None = None
    release_date: date | None = None


class MovieCityShowtimeSearchOut(BaseModel):
    cinema_id: int
    cinema: str
    movie_id: int
    title: str
    title_en: str | None = None
    start_time: list[str] = Field(default_factory=list)
