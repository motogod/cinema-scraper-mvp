from datetime import datetime, date, time
from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class CinemaChain(Base):
    __tablename__ = "cinema_chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cinemas: Mapped[list["Cinema"]] = relationship(back_populates="chain_record")


class Cinema(Base):
    __tablename__ = "cinemas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chain: Mapped[str] = mapped_column(String(80), index=True)
    chain_id: Mapped[int | None] = mapped_column(ForeignKey("cinema_chains.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_cinema_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    chain_record: Mapped[CinemaChain | None] = relationship(back_populates="cinemas")
    showtimes: Mapped[list["Showtime"]] = relationship(back_populates="cinema")

    __table_args__ = (
        UniqueConstraint("chain", "name", name="uq_cinemas_chain_name"),
        UniqueConstraint("chain_id", "name", name="uq_cinemas_chain_id_name"),
    )


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    title_zh: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    title_en: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    original_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    still_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[str | None] = mapped_column(String(50), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    director: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cast: Mapped[str | None] = mapped_column("cast_members", Text, nullable=True)
    cast_photo_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    trailer_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    trailer_video_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    youtube_thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_movie_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    showtimes: Mapped[list["Showtime"]] = relationship(back_populates="movie")
    sources: Mapped[list["MovieSource"]] = relationship(back_populates="movie")

    __table_args__ = (UniqueConstraint("title", name="uq_movies_title"),)

    @property
    def movie_id(self) -> int:
        return self.id


class MovieSource(Base):
    __tablename__ = "movie_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    source_movie_id: Mapped[str] = mapped_column(String(120), index=True)
    source_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_original_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    detail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    movie: Mapped[Movie] = relationship(back_populates="sources")

    __table_args__ = (
        UniqueConstraint("source", "source_movie_id", name="uq_movie_sources_source_movie_id"),
    )


class Showtime(Base):
    __tablename__ = "showtimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cinema_id: Mapped[int] = mapped_column(ForeignKey("cinemas.id", ondelete="CASCADE"), index=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    show_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time, index=True)
    hall_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    format: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    auditorium_brand: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    projection_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    audio_language: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    subtitle_language: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    booking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    source_showtime_id: Mapped[str] = mapped_column(String(300), index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cinema: Mapped[Cinema] = relationship(back_populates="showtimes")
    movie: Mapped[Movie] = relationship(back_populates="showtimes")

    __table_args__ = (
        UniqueConstraint("source", "source_showtime_id", name="uq_showtimes_source_showtime_id"),
    )
