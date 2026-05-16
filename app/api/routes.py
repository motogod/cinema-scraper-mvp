import re
from datetime import date, time
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models import Cinema, CinemaChain, Movie, Showtime
from app.schemas.cinema import (
    CinemaChainOut,
    CinemaOut,
    GroupedShowtimeMovieOut,
    MovieCityShowtimeSearchOut,
    MovieDetailOut,
    MovieOut,
    MovieSearchOut,
    ShowtimeOut,
)

router = APIRouter()


CITY_ALIASES = {
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


def normalize_city(city: str) -> str:
    city = city.strip()
    return CITY_ALIASES.get(city, city)


def normalize_movie_search_text(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "")).lower()


@router.get("/chains", response_model=list[CinemaChainOut])
def list_chains(db: Session = Depends(get_db)):
    return db.scalars(select(CinemaChain).order_by(CinemaChain.name)).all()


@router.get("/cinemas", response_model=list[CinemaOut])
def list_cinemas(
    chain_id: int | None = None,
    city: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Cinema).order_by(Cinema.city, Cinema.name)
    if chain_id:
        stmt = stmt.where(Cinema.chain_id == chain_id)
    if city:
        stmt = stmt.where(Cinema.city == normalize_city(city))
    return db.scalars(stmt).all()


@router.get("/movies", response_model=list[MovieOut])
def list_movies(db: Session = Depends(get_db)):
    return db.scalars(select(Movie).order_by(Movie.title)).all()


@router.get("/movies/search", response_model=list[MovieSearchOut])
def search_movies(
    movie_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    movie_key = normalize_movie_search_text(movie_name)
    if not movie_key:
        raise HTTPException(status_code=400, detail="movie_name must not be blank")

    results: list[MovieSearchOut] = []
    for movie in db.scalars(select(Movie).order_by(Movie.title)).all():
        searchable_titles = [
            movie.title,
            movie.title_zh,
            movie.title_en,
            movie.original_title,
        ]
        if not any(movie_key in normalize_movie_search_text(title) for title in searchable_titles):
            continue
        results.append(
            MovieSearchOut(
                movie_id=movie.id,
                title=movie.title,
                title_en=movie.title_en or movie.original_title,
                poster_url=movie.poster_url,
                genre=movie.genre,
                rating=movie.rating,
                duration_minutes=movie.duration_minutes,
                release_date=movie.release_date,
            )
        )
    return results


@router.get("/movies/search-showtimes", response_model=list[MovieCityShowtimeSearchOut])
def search_movie_showtimes_by_city(
    movie_name: str = Query(..., min_length=1),
    city: str = Query(..., min_length=1),
    date_from: date = Query(...),
    date_to: date = Query(...),
    time_from: time | None = Query(default=None),
    time_to: time | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must be on or after date_from")

    normalized_city = normalize_city(city)
    movie_key = normalize_movie_search_text(movie_name)
    if not movie_key:
        raise HTTPException(status_code=400, detail="movie_name must not be blank")
    stmt = (
        select(Showtime)
        .join(Showtime.movie)
        .join(Showtime.cinema)
        .options(joinedload(Showtime.movie), joinedload(Showtime.cinema))
        .where(
            Cinema.city == normalized_city,
            Showtime.show_date >= date_from,
            Showtime.show_date <= date_to,
        )
        .order_by(Movie.title, Cinema.name, Showtime.show_date, Showtime.start_time)
    )
    if time_from and time_to and time_to < time_from:
        stmt = stmt.where(or_(Showtime.start_time >= time_from, Showtime.start_time <= time_to))
    elif time_from:
        stmt = stmt.where(Showtime.start_time >= time_from)
    elif time_to:
        stmt = stmt.where(Showtime.start_time <= time_to)

    output: dict[tuple[int, int], MovieCityShowtimeSearchOut] = {}
    for showtime in db.scalars(stmt).all():
        movie = showtime.movie
        searchable_titles = [
            movie.title,
            movie.title_zh,
            movie.title_en,
            movie.original_title,
        ]
        if not any(movie_key in normalize_movie_search_text(title) for title in searchable_titles):
            continue

        cinema = showtime.cinema
        group_key = (cinema.id, movie.id)
        group = output.get(group_key)
        if group is None:
            group = MovieCityShowtimeSearchOut(
                cinema_id=cinema.id,
                cinema=cinema.name,
                movie_id=movie.id,
                title=movie.title,
                title_en=movie.title_en or movie.original_title,
                start_time=[],
            )
            output[group_key] = group
        show_time = showtime.start_time.strftime("%H:%M")
        if show_time not in group.start_time:
            group.start_time.append(show_time)

    return list(output.values())


@router.get("/movies/{movie_id}", response_model=MovieDetailOut)
def get_movie(movie_id: int, db: Session = Depends(get_db)):
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


@router.get("/showtimes", response_model=list[ShowtimeOut])
def list_showtimes(
    cinema_id: int | None = None,
    movie_id: int | None = None,
    show_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Showtime)
        .options(joinedload(Showtime.cinema), joinedload(Showtime.movie))
        .order_by(Showtime.show_date, Showtime.start_time)
    )
    if cinema_id:
        stmt = stmt.where(Showtime.cinema_id == cinema_id)
    if movie_id:
        stmt = stmt.where(Showtime.movie_id == movie_id)
    if show_date:
        stmt = stmt.where(Showtime.show_date == show_date)
    return db.scalars(stmt).all()


@router.get("/showtimes/grouped", response_model=list[GroupedShowtimeMovieOut])
def list_grouped_showtimes(
    cinema_id: int,
    show_date: date = Query(...),
    db: Session = Depends(get_db),
):
    cinema = db.get(Cinema, cinema_id)
    if cinema is None:
        raise HTTPException(status_code=404, detail="Cinema not found")

    cinema_ids = [cinema.id]
    if cinema.address:
        sibling_stmt = select(Cinema.id).where(Cinema.address == cinema.address)
        if cinema.chain_id:
            sibling_stmt = sibling_stmt.where(Cinema.chain_id == cinema.chain_id)
        else:
            sibling_stmt = sibling_stmt.where(Cinema.chain == cinema.chain)
        sibling_ids = db.scalars(
            sibling_stmt
        ).all()
        cinema_ids = sorted(set(sibling_ids) | {cinema.id})

    stmt = (
        select(Showtime)
        .options(joinedload(Showtime.movie), joinedload(Showtime.cinema))
        .where(Showtime.cinema_id.in_(cinema_ids), Showtime.show_date == show_date)
        .order_by(Showtime.start_time)
    )

    movies_by_version: dict[tuple[int, str], GroupedShowtimeMovieOut] = {}
    for showtime in db.scalars(stmt).all():
        movie = showtime.movie
        show_time = showtime.start_time.strftime("%H:%M")
        format_label = (
            showtime.version_label
            or showtime.format
            or showtime.language
            or "一般"
        )
        group_key = (movie.id, format_label)
        if group_key not in movies_by_version:
            movies_by_version[group_key] = GroupedShowtimeMovieOut(
                id=movie.id,
                title=movie.title,
                original_title=movie.original_title,
                poster_url=movie.poster_url,
                rating=movie.rating,
                genre=movie.genre,
                format=format_label,
                start_time=[],
            )
        movie_with_times = movies_by_version[group_key]
        if show_time not in movie_with_times.start_time:
            movie_with_times.start_time.append(show_time)

    return list(movies_by_version.values())
