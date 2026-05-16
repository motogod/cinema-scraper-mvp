import argparse
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Movie, MovieSource, Showtime
from app.services.importer import (
    _is_same_movie_title,
    _movie_merge_updates,
    _movie_title_keys,
)


@dataclass
class DuplicateGroup:
    keeper: Movie
    duplicates: list[Movie]


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge duplicate movie rows by canonical title keys.")
    parser.add_argument("--apply", action="store_true", help="Actually update the database.")
    args = parser.parse_args()

    with SessionLocal() as db:
        groups = find_duplicate_groups(db)
        if not groups:
            print("No duplicate movie groups found.")
            return

        for group in groups:
            print_group(group)

        if not args.apply:
            print(f"\nDry run only. Add --apply to merge {len(groups)} group(s).")
            return

        for group in groups:
            merge_group(db, group)
        db.commit()
        print(f"\nMerged {len(groups)} duplicate movie group(s).")


def find_duplicate_groups(db: Session) -> list[DuplicateGroup]:
    movies = db.scalars(select(Movie).order_by(Movie.id)).all()
    remaining = list(movies)
    groups: list[DuplicateGroup] = []

    while remaining:
        movie = remaining.pop(0)
        movie_keys = _movie_title_keys(movie.title, movie.title_zh, movie.title_en, movie.original_title)
        matches: list[Movie] = []

        for candidate in list(remaining):
            candidate_keys = _movie_title_keys(
                candidate.title,
                candidate.title_zh,
                candidate.title_en,
                candidate.original_title,
            )
            if _is_same_movie_title(movie_keys, candidate_keys):
                matches.append(candidate)
                remaining.remove(candidate)

        if matches:
            candidates = [movie, *matches]
            keeper = max(candidates, key=_movie_quality_score)
            duplicates = [candidate for candidate in candidates if candidate.id != keeper.id]
            groups.append(DuplicateGroup(keeper=keeper, duplicates=duplicates))

    return groups


def merge_group(db: Session, group: DuplicateGroup) -> None:
    keeper = group.keeper
    duplicate_ids = [movie.id for movie in group.duplicates]
    best = max([keeper, *group.duplicates], key=_movie_quality_score)
    updates = _merged_movie_values(keeper, best)

    db.execute(update(Showtime).where(Showtime.movie_id.in_(duplicate_ids)).values(movie_id=keeper.id))
    db.execute(update(MovieSource).where(MovieSource.movie_id.in_(duplicate_ids)).values(movie_id=keeper.id))
    db.execute(delete(Movie).where(Movie.id.in_(duplicate_ids)))
    if updates:
        db.execute(update(Movie).where(Movie.id == keeper.id).values(**updates))


def _merged_movie_values(keeper: Movie, best: Movie) -> dict:
    updates = _movie_merge_updates(keeper, best)
    for field in ["title", "title_zh", "title_en", "original_title"]:
        value = getattr(best, field)
        if value and getattr(keeper, field) != value:
            updates[field] = value
    return updates


def _movie_quality_score(movie: Movie) -> tuple[int, int, int, int]:
    rich_fields = [
        movie.poster_url,
        movie.release_date,
        movie.duration_minutes,
        movie.rating,
        movie.genre,
        movie.description,
        movie.director,
        movie.cast,
        movie.trailer_url,
        movie.detail_url,
    ]
    title_has_cjk = 1 if _has_cjk(movie.title or "") else 0
    metadata_score = sum(1 for value in rich_fields if value not in (None, "", []))
    source_count = len(movie.sources or [])
    showtime_count = len(movie.showtimes or [])
    return (metadata_score, title_has_cjk, source_count + showtime_count, -movie.id)


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def print_group(group: DuplicateGroup) -> None:
    print(f"\nKeep movie_id={group.keeper.id}: {group.keeper.title}")
    for movie in group.duplicates:
        print(f"  Merge movie_id={movie.id}: {movie.title}")


if __name__ == "__main__":
    main()
