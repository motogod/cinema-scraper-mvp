from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy import delete, select, text, update
import re

from app.models import Cinema, CinemaChain, Movie, MovieSource, Showtime
from app.scrapers.base import ScrapedShowtime


def import_showtimes(db: Session, items: list[ScrapedShowtime]) -> int:
    ensure_schema(db)
    count = 0
    for item in items:
        cinema_id = _upsert_cinema(db, item)
        movie_id = _upsert_movie(db, item)
        stmt = insert(Showtime).values(
            cinema_id=cinema_id,
            movie_id=movie_id,
            show_date=item.show_date,
            start_time=item.start_time,
            hall_name=item.hall_name,
            format=item.format,
            language=item.language,
            version_label=item.version_label,
            auditorium_brand=item.auditorium_brand,
            projection_type=item.projection_type,
            audio_language=item.audio_language,
            subtitle_language=item.subtitle_language,
            booking_url=item.booking_url,
            source_payload=item.source_payload,
            source=item.source,
            source_showtime_id=item.source_showtime_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Showtime.source, Showtime.source_showtime_id],
            set_={
                "cinema_id": cinema_id,
                "movie_id": movie_id,
                "show_date": item.show_date,
                "start_time": item.start_time,
                "hall_name": item.hall_name,
                "format": item.format,
                "language": item.language,
                "version_label": item.version_label,
                "auditorium_brand": item.auditorium_brand,
                "projection_type": item.projection_type,
                "audio_language": item.audio_language,
                "subtitle_language": item.subtitle_language,
                "booking_url": item.booking_url,
                "source_payload": item.source_payload,
            },
        ).returning(Showtime.id)
        db.execute(stmt).scalar_one()
        count += 1
    db.commit()
    return count


def replace_showtimes(db: Session, items: list[ScrapedShowtime], source: str) -> int:
    ensure_schema(db)
    db.execute(delete(Showtime).where(Showtime.source == source))
    db.execute(delete(MovieSource).where(MovieSource.source == source))
    db.commit()
    return import_showtimes(db, items)


def _delete_orphan_movies(db: Session) -> None:
    db.execute(
        delete(Movie).where(
            ~select(Showtime.id).where(Showtime.movie_id == Movie.id).exists()
        )
    )


def _upsert_cinema(db: Session, item: ScrapedShowtime) -> int:
    cinema = item.cinema
    chain_id = _upsert_chain(db, cinema.chain)
    if cinema.source_cinema_id:
        existing_id = db.execute(
            select(Cinema.id).where(
                Cinema.chain_id == chain_id,
                Cinema.source_cinema_id == cinema.source_cinema_id,
            )
        ).scalar_one_or_none()
        if not existing_id:
            existing_id = db.execute(
                select(Cinema.id).where(
                    Cinema.chain == cinema.chain,
                    Cinema.source_cinema_id == cinema.source_cinema_id,
                )
            ).scalar_one_or_none()
        if existing_id:
            conflicting_name_id = db.execute(
                select(Cinema.id).where(
                    Cinema.chain == cinema.chain,
                    Cinema.name == cinema.name,
                    Cinema.id != existing_id,
                )
            ).scalar_one_or_none()
            if conflicting_name_id:
                db.execute(
                    update(Cinema)
                    .where(Cinema.id == existing_id)
                    .values(
                        chain_id=chain_id,
                        chain=cinema.chain,
                        city=cinema.city,
                        address=cinema.address,
                        source_cinema_id=cinema.source_cinema_id,
                    )
                )
                return existing_id

            db.execute(
                update(Cinema)
                .where(Cinema.id == existing_id)
                .values(
                    chain_id=chain_id,
                    chain=cinema.chain,
                    name=cinema.name,
                    city=cinema.city,
                    address=cinema.address,
                    source_cinema_id=cinema.source_cinema_id,
                )
            )
            return existing_id

    stmt = insert(Cinema).values(
        chain_id=chain_id,
        chain=cinema.chain,
        name=cinema.name,
        city=cinema.city,
        address=cinema.address,
        source_cinema_id=cinema.source_cinema_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Cinema.chain, Cinema.name],
        set_={
            "chain_id": chain_id,
            "city": cinema.city,
            "address": cinema.address,
            "source_cinema_id": cinema.source_cinema_id,
        },
    ).returning(Cinema.id)
    return db.execute(stmt).scalar_one()


def _upsert_chain(db: Session, chain_name: str) -> int:
    code = _chain_code(chain_name)
    stmt = insert(CinemaChain).values(
        code=code,
        name=chain_name,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CinemaChain.code],
        set_={
            "name": chain_name,
        },
    ).returning(CinemaChain.id)
    return db.execute(stmt).scalar_one()


def _chain_code(chain_name: str) -> str:
    return (
        chain_name.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _upsert_movie(db: Session, item: ScrapedShowtime) -> int:
    movie = item.movie
    existing_id = _movie_id_from_source(db, item)
    if not existing_id:
        existing_id = _movie_id_from_title(db, movie.title, movie.title_zh, movie.title_en, movie.original_title)

    if existing_id:
        existing = db.get(Movie, existing_id)
        updates = _movie_merge_updates(existing, movie) if existing else {}
        if updates:
            db.execute(update(Movie).where(Movie.id == existing_id).values(**updates))
        _upsert_movie_source(db, existing_id, item)
        return existing_id

    stmt = insert(Movie).values(**_movie_insert_values(movie)).returning(Movie.id)
    movie_id = db.execute(stmt).scalar_one()
    _upsert_movie_source(db, movie_id, item)
    return movie_id


def _movie_id_from_source(db: Session, item: ScrapedShowtime) -> int | None:
    if not item.movie.source_movie_id:
        return None
    return db.execute(
        select(MovieSource.movie_id).where(
            MovieSource.source == item.source,
            MovieSource.source_movie_id == item.movie.source_movie_id,
        )
    ).scalar_one_or_none()


def _movie_id_from_title(
    db: Session,
    *titles: str | None,
) -> int | None:
    incoming = _movie_title_keys(*titles)
    if not incoming["all"]:
        return None
    movies = db.scalars(select(Movie)).all()
    for movie in movies:
        existing = _movie_title_keys(
            movie.title,
            movie.title_zh,
            movie.title_en,
            movie.original_title,
        )
        if _is_same_movie_title(incoming, existing):
            return movie.id
    return None


def _movie_title_keys(*titles: str | None) -> dict[str, set[str]]:
    zh: set[str] = set()
    en: set[str] = set()
    for title in titles:
        key = _movie_key(title)
        if not key or len(key) < 2:
            continue
        if _has_cjk(title or ""):
            zh.add(key)
        elif len(key) >= 4:
            en.add(key)
    return {
        "zh": zh,
        "en": en,
        "all": zh | en,
    }


def _is_same_movie_title(incoming: dict[str, set[str]], existing: dict[str, set[str]]) -> bool:
    if incoming["zh"] and existing["zh"] and incoming["zh"] & existing["zh"]:
        return True

    if incoming["en"] and existing["en"] and incoming["en"] & existing["en"]:
        return not _has_conflicting_zh_title(incoming, existing)

    return False


def _has_conflicting_zh_title(incoming: dict[str, set[str]], existing: dict[str, set[str]]) -> bool:
    if not incoming["zh"] or not existing["zh"]:
        return False
    if incoming["zh"] & existing["zh"]:
        return False
    return not any(
        _contains_title_variant(left, right)
        for left in incoming["zh"]
        for right in existing["zh"]
    )


def _contains_title_variant(left: str, right: str) -> bool:
    return len(left) >= 4 and len(right) >= 4 and (left in right or right in left)


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _movie_key(title: str | None) -> str:
    if not title:
        return ""
    title = (
        title.replace("Ⅰ", "I")
        .replace("Ⅱ", "II")
        .replace("Ⅲ", "III")
        .replace("Ⅳ", "IV")
        .replace("Ⅴ", "V")
        .replace("Ⅵ", "VI")
        .replace("Ⅶ", "VII")
        .replace("Ⅷ", "VIII")
        .replace("Ⅸ", "IX")
        .replace("Ⅹ", "X")
    )
    return re.sub(r"[：:：－—\-・·\s　！!？?（）()《》「」『』,.，。/\\]+", "", title).lower()


def _movie_insert_values(movie) -> dict:
    return {
        "title": movie.title,
        "title_zh": movie.title_zh,
        "title_en": movie.title_en,
        "original_title": movie.original_title,
        "poster_url": movie.poster_url,
        "still_urls": movie.still_urls,
        "release_date": movie.release_date,
        "duration_minutes": movie.duration_minutes,
        "rating": movie.rating,
        "genre": movie.genre,
        "description": movie.description,
        "director": movie.director,
        "cast": movie.cast,
        "cast_photo_urls": movie.cast_photo_urls,
        "trailer_url": movie.trailer_url,
        "detail_url": movie.detail_url,
        "source_movie_id": movie.source_movie_id,
    }


def _movie_merge_updates(existing: Movie, incoming) -> dict:
    updates = {}
    for field in [
        "title_zh",
        "title_en",
        "original_title",
        "poster_url",
        "release_date",
        "duration_minutes",
        "rating",
        "genre",
        "description",
        "director",
        "cast",
        "trailer_url",
        "detail_url",
        "source_movie_id",
    ]:
        if _is_blank(getattr(existing, field)) and not _is_blank(getattr(incoming, field)):
            updates[field] = getattr(incoming, field)

    still_urls = _better_list(existing.still_urls, incoming.still_urls)
    if still_urls is not existing.still_urls:
        updates["still_urls"] = still_urls

    cast_photo_urls = _better_list(existing.cast_photo_urls, incoming.cast_photo_urls)
    if cast_photo_urls is not existing.cast_photo_urls:
        updates["cast_photo_urls"] = cast_photo_urls

    return updates


def _is_blank(value) -> bool:
    return value is None or value == "" or value == []


def _better_list(existing: list | None, incoming: list | None) -> list | None:
    existing_len = len(existing or [])
    incoming_len = len(incoming or [])
    return incoming if incoming_len > existing_len else existing


def _upsert_movie_source(db: Session, movie_id: int, item: ScrapedShowtime) -> None:
    movie = item.movie
    if not movie.source_movie_id:
        return
    stmt = insert(MovieSource).values(
        movie_id=movie_id,
        source=item.source,
        source_movie_id=movie.source_movie_id,
        source_title=movie.title,
        source_original_title=movie.original_title or movie.title_en,
        detail_url=movie.detail_url,
        source_payload=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[MovieSource.source, MovieSource.source_movie_id],
        set_={
            "movie_id": movie_id,
            "source_title": movie.title,
            "source_original_title": movie.original_title or movie.title_en,
            "detail_url": movie.detail_url,
        },
    )
    db.execute(stmt)


def ensure_schema(db: Session) -> None:
    """Keep local MVP databases compatible without a migration framework."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS cinema_chains (
            id SERIAL PRIMARY KEY,
            code VARCHAR(80) UNIQUE NOT NULL,
            name VARCHAR(120) UNIQUE NOT NULL,
            website_url TEXT,
            source_payload JSON,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
        """,
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS title_zh VARCHAR(300)",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS title_en VARCHAR(300)",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS still_urls JSON",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS release_date DATE",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS director VARCHAR(300)",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS cast_members TEXT",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS cast_photo_urls JSON",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS trailer_url TEXT",
        "ALTER TABLE movies ADD COLUMN IF NOT EXISTS detail_url TEXT",
        """
        CREATE TABLE IF NOT EXISTS movie_sources (
            id SERIAL PRIMARY KEY,
            movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
            source VARCHAR(80) NOT NULL,
            source_movie_id VARCHAR(120) NOT NULL,
            source_title VARCHAR(300),
            source_original_title VARCHAR(300),
            detail_url TEXT,
            source_payload JSON,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            CONSTRAINT uq_movie_sources_source_movie_id UNIQUE (source, source_movie_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_movie_sources_movie_id ON movie_sources (movie_id)",
        "CREATE INDEX IF NOT EXISTS ix_movie_sources_source ON movie_sources (source)",
        "CREATE INDEX IF NOT EXISTS ix_movie_sources_source_movie_id ON movie_sources (source_movie_id)",
        """
        INSERT INTO movie_sources (
            movie_id,
            source,
            source_movie_id,
            source_title,
            source_original_title,
            detail_url
        )
        SELECT
            id,
            'legacy',
            source_movie_id,
            title,
            original_title,
            detail_url
        FROM movies
        WHERE source_movie_id IS NOT NULL
        ON CONFLICT (source, source_movie_id) DO NOTHING
        """,
        "ALTER TABLE cinemas ADD COLUMN IF NOT EXISTS chain_id INTEGER",
        "ALTER TABLE showtimes ADD COLUMN IF NOT EXISTS version_label VARCHAR(160)",
        "ALTER TABLE showtimes ADD COLUMN IF NOT EXISTS auditorium_brand VARCHAR(80)",
        "ALTER TABLE showtimes ADD COLUMN IF NOT EXISTS projection_type VARCHAR(80)",
        "ALTER TABLE showtimes ADD COLUMN IF NOT EXISTS audio_language VARCHAR(80)",
        "ALTER TABLE showtimes ADD COLUMN IF NOT EXISTS subtitle_language VARCHAR(80)",
        "ALTER TABLE showtimes ADD COLUMN IF NOT EXISTS source_payload JSON",
        "CREATE INDEX IF NOT EXISTS ix_showtimes_auditorium_brand ON showtimes (auditorium_brand)",
        "CREATE INDEX IF NOT EXISTS ix_showtimes_projection_type ON showtimes (projection_type)",
        "CREATE INDEX IF NOT EXISTS ix_showtimes_audio_language ON showtimes (audio_language)",
        "CREATE INDEX IF NOT EXISTS ix_showtimes_subtitle_language ON showtimes (subtitle_language)",
        "CREATE INDEX IF NOT EXISTS ix_cinemas_chain_id ON cinemas (chain_id)",
        """
        INSERT INTO cinema_chains (code, name)
        SELECT DISTINCT
            replace(lower(chain), ' ', '_') AS code,
            chain AS name
        FROM cinemas
        WHERE chain IS NOT NULL
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
        """,
        """
        UPDATE cinemas
        SET chain_id = cinema_chains.id
        FROM cinema_chains
        WHERE cinemas.chain_id IS NULL
            AND cinema_chains.code = replace(lower(cinemas.chain), ' ', '_')
        """,
    ]
    for statement in statements:
        db.execute(text(statement))
