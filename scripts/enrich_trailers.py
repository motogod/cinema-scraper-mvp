import argparse
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Movie
from app.services.importer import (
    _is_same_movie_title,
    _movie_title_keys,
    ensure_schema,
)
from app.utils.trailers import youtube_video_id, youtube_watch_url
from app.utils.youtube_api import YouTubeApiClient, YouTubeApiError, YouTubeVideoCandidate
from app.utils.youtube_web import YouTubeWebSearchClient, YouTubeWebSearchError


@dataclass
class TrailerUpdate:
    movie: Movie
    source: Movie | None
    trailer_url: str | None
    trailer_video_id: str | None
    source_label: str
    score: int | None = None
    matched_title: str | None = None
    matched_channel: str | None = None


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Backfill missing trailers from locally known movies with matching titles."
    )
    parser.add_argument("--apply", action="store_true", help="Actually update the database.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of movies to update.",
    )
    parser.add_argument(
        "--youtube-api",
        action="store_true",
        help="Search YouTube Data API for movies still missing trailers.",
    )
    parser.add_argument(
        "--youtube-web",
        action="store_true",
        help="Search YouTube web pages and use the first video result for missing trailers.",
    )
    parser.add_argument(
        "--youtube-api-key",
        default=None,
        help="YouTube Data API key. Defaults to YOUTUBE_API_KEY.",
    )
    parser.add_argument(
        "--youtube-limit",
        type=int,
        default=None,
        help="Maximum number of YouTube API matches to update.",
    )
    parser.add_argument(
        "--youtube-min-score",
        type=int,
        default=7,
        help="Minimum confidence score for YouTube API matches.",
    )
    parser.add_argument(
        "--youtube-max-results",
        type=int,
        default=5,
        help="YouTube search results to inspect per movie.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        ensure_schema(db)
        updates = find_trailer_updates(db, limit=args.limit)
        if args.youtube_api:
            api_key = args.youtube_api_key or os.getenv("YOUTUBE_API_KEY")
            if not api_key:
                raise SystemExit("Missing YouTube API key. Set YOUTUBE_API_KEY or pass --youtube-api-key.")
            client = YouTubeApiClient(api_key)
            try:
                updates.extend(
                    find_youtube_trailer_updates(
                        db,
                        client,
                        existing_updates=updates,
                        limit=args.youtube_limit,
                        min_score=args.youtube_min_score,
                        max_results=args.youtube_max_results,
                    )
                )
            except YouTubeApiError as exc:
                raise SystemExit(str(exc)) from exc
        if args.youtube_web:
            client = YouTubeWebSearchClient()
            try:
                updates.extend(
                    find_youtube_web_trailer_updates(
                        db,
                        client,
                        existing_updates=updates,
                        limit=args.youtube_limit,
                    )
                )
            except YouTubeWebSearchError as exc:
                raise SystemExit(str(exc)) from exc
        if not updates:
            print("No trailer updates found.")
            return

        for item in updates:
            print(
                f"movie_id={item.movie.id} {item.movie.title} <- {item.source_label} "
                f"url={item.trailer_url or '-'} video_id={item.trailer_video_id or '-'}"
            )
            if item.score is not None:
                print(
                    f"  score={item.score} title={item.matched_title or '-'} "
                    f"channel={item.matched_channel or '-'}"
                )

        if not args.apply:
            print(f"\nDry run only. Add --apply to update {len(updates)} movie(s).")
            return

        apply_updates(db, updates)
        db.commit()
        print(f"\nUpdated {len(updates)} movie(s).")


def find_trailer_updates(db: Session, limit: int | None = None) -> list[TrailerUpdate]:
    movies = db.scalars(select(Movie).order_by(Movie.id)).all()
    candidates = [movie for movie in movies if _has_trailer_data(movie)]
    updates: list[TrailerUpdate] = []

    for movie in movies:
        if not _needs_trailer_update(movie):
            continue

        own_video_id = youtube_video_id(movie.trailer_url)
        if movie.trailer_url and own_video_id and not movie.trailer_video_id:
            updates.append(
                TrailerUpdate(
                    movie=movie,
                    source=None,
                    trailer_url=movie.trailer_url,
                    trailer_video_id=own_video_id,
                    source_label="own trailer_url",
                )
            )
        else:
            source = _matching_trailer_source(movie, candidates)
            if not source:
                continue
            trailer_url = movie.trailer_url or source.trailer_url or youtube_watch_url(source.trailer_video_id)
            trailer_video_id = (
                movie.trailer_video_id
                or source.trailer_video_id
                or youtube_video_id(source.trailer_url)
            )
            if not trailer_url and trailer_video_id:
                trailer_url = youtube_watch_url(trailer_video_id)
            updates.append(
                TrailerUpdate(
                    movie=movie,
                    source=source,
                    trailer_url=trailer_url,
                    trailer_video_id=trailer_video_id,
                    source_label=f"movie_id={source.id}",
                )
            )

        if limit is not None and len(updates) >= limit:
            break

    return updates


def find_youtube_trailer_updates(
    db: Session,
    client: YouTubeApiClient,
    existing_updates: list[TrailerUpdate],
    limit: int | None = None,
    min_score: int = 7,
    max_results: int = 5,
) -> list[TrailerUpdate]:
    pending_movie_ids = {item.movie.id for item in existing_updates}
    movies = db.scalars(
        select(Movie)
        .where(Movie.trailer_video_id.is_(None))
        .order_by(Movie.id)
    ).all()
    updates: list[TrailerUpdate] = []
    print(f"YouTube API candidates missing trailer_video_id: {len(movies)}")

    for movie in movies:
        if movie.id in pending_movie_ids or movie.trailer_video_id:
            continue

        query = _youtube_query(movie)
        if not query:
            continue

        candidates = client.search_videos(query, max_results=max_results)
        best = _best_youtube_candidate(movie, candidates)
        if not best:
            continue

        candidate, score = best
        if score < min_score:
            continue

        updates.append(
            TrailerUpdate(
                movie=movie,
                source=None,
                trailer_url=youtube_watch_url(candidate.video_id),
                trailer_video_id=candidate.video_id,
                source_label=f"YouTube API query={query!r}",
                score=score,
                matched_title=candidate.title,
                matched_channel=candidate.channel_title,
            )
        )
        if limit is not None and len(updates) >= limit:
            break

    return updates


def find_youtube_web_trailer_updates(
    db: Session,
    client: YouTubeWebSearchClient,
    existing_updates: list[TrailerUpdate],
    limit: int | None = None,
) -> list[TrailerUpdate]:
    pending_movie_ids = {item.movie.id for item in existing_updates}
    movies = db.scalars(
        select(Movie)
        .where(Movie.trailer_video_id.is_(None))
        .order_by(Movie.id)
    ).all()
    updates: list[TrailerUpdate] = []
    print(f"YouTube web candidates missing trailer_video_id: {len(movies)}")

    for movie in movies:
        if movie.id in pending_movie_ids or movie.trailer_video_id:
            continue

        query = _youtube_query(movie)
        if not query:
            continue

        result = client.first_video(query)
        if not result:
            continue

        updates.append(
            TrailerUpdate(
                movie=movie,
                source=None,
                trailer_url=youtube_watch_url(result.video_id),
                trailer_video_id=result.video_id,
                source_label=f"YouTube web first result query={query!r}",
                matched_title=result.title,
                matched_channel=result.channel_title,
            )
        )
        if limit is not None and len(updates) >= limit:
            break

    return updates


def apply_updates(db: Session, updates: list[TrailerUpdate]) -> None:
    for item in updates:
        values = {}
        if item.trailer_url and (
            not item.movie.trailer_url
            or (item.trailer_video_id and not youtube_video_id(item.movie.trailer_url))
        ):
            values["trailer_url"] = item.trailer_url
        if not item.movie.trailer_video_id and item.trailer_video_id:
            values["trailer_video_id"] = item.trailer_video_id
        if values:
            db.execute(update(Movie).where(Movie.id == item.movie.id).values(**values))


def _matching_trailer_source(movie: Movie, candidates: list[Movie]) -> Movie | None:
    movie_keys = _movie_title_keys(
        movie.title,
        movie.title_zh,
        movie.title_en,
        movie.original_title,
    )
    matches: list[Movie] = []
    for candidate in candidates:
        if candidate.id == movie.id:
            continue
        candidate_keys = _movie_title_keys(
            candidate.title,
            candidate.title_zh,
            candidate.title_en,
            candidate.original_title,
        )
        if _is_same_movie_title(movie_keys, candidate_keys):
            matches.append(candidate)
    return max(matches, key=_trailer_quality_score) if matches else None


def _needs_trailer_update(movie: Movie) -> bool:
    return not movie.trailer_url or not movie.trailer_video_id


def _has_trailer_data(movie: Movie) -> bool:
    return bool(movie.trailer_url or movie.trailer_video_id)


def _trailer_quality_score(movie: Movie) -> tuple[int, int, int, int]:
    has_video_id = 1 if movie.trailer_video_id or youtube_video_id(movie.trailer_url) else 0
    has_youtube_url = 1 if youtube_video_id(movie.trailer_url) else 0
    has_url = 1 if movie.trailer_url else 0
    metadata = sum(
        1
        for value in [
            movie.poster_url,
            movie.release_date,
            movie.duration_minutes,
            movie.rating,
            movie.description,
            movie.director,
            movie.cast,
        ]
        if value not in (None, "", [])
    )
    return (has_video_id, has_youtube_url, has_url, metadata)


def _youtube_query(movie: Movie) -> str | None:
    title = movie.title_zh or movie.title or movie.original_title or movie.title_en
    title = _movie_search_title(title)
    title = _clean_query_text(title)
    return f"{title} 預告片" if title else None


def _best_youtube_candidate(
    movie: Movie,
    candidates: list[YouTubeVideoCandidate],
) -> tuple[YouTubeVideoCandidate, int] | None:
    scored = [(candidate, _youtube_candidate_score(movie, candidate)) for candidate in candidates]
    scored = [item for item in scored if item[1] > 0]
    return max(scored, key=lambda item: item[1]) if scored else None


def _youtube_candidate_score(movie: Movie, candidate: YouTubeVideoCandidate) -> int:
    title = _normalize_for_match(candidate.title)
    channel = _normalize_for_match(candidate.channel_title)
    movie_titles = [
        _normalize_for_match(value)
        for value in [movie.title, movie.title_zh, movie.title_en, movie.original_title]
        if value
    ]

    score = 0
    if any(movie_title and movie_title in title for movie_title in movie_titles):
        score += 5
    if any(keyword in title for keyword in ["預告", "trailer", "teaser", "前導"]):
        score += 3
    if any(keyword in title for keyword in ["正式預告", "official trailer", "official teaser"]):
        score += 2
    if any(keyword in channel for keyword in ["官方", "影業", "電影", "pictures", "films", "movie"]):
        score += 1
    if any(keyword in title for keyword in ["影評", "解析", "懶人包", "reaction", "review", "ending"]):
        score -= 5
    if any(keyword in title for keyword in ["主題曲", "片段", "花絮", "訪談", "clip", "soundtrack"]):
        score -= 3
    return score


def _clean_query_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _movie_search_title(value: str | None) -> str | None:
    if not value:
        return None

    bracket_titles = re.findall(r"《([^》]+)》", value)
    if bracket_titles:
        return bracket_titles[-1]

    text = re.sub(r"^【[^】]+】", "", value).strip()
    return text or value


def _normalize_for_match(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value).casefold()


if __name__ == "__main__":
    main()
