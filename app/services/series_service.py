import random
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.models import SeriesEpisode, SeriesStatus, Short, StorySeries

SERIES_EPISODE_RANGE = (4, 5)
SERIES_NAME_WORDS_A = [
    "Night", "Shadow", "Silent", "Broken", "Whisper", "Crimson", "Vanishing", "Grim",
]
SERIES_NAME_WORDS_B = [
    "Protocol", "Archive", "Corridor", "Signal", "Casefile", "Ledger", "Ritual", "Transmission",
]


@dataclass
class SeriesAssignment:
    series_id: int
    series_name: str
    title_prefix: str
    playlist_name: str
    episode_number: int
    planned_episodes: int


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SeriesService:
    def assign_short(self, session, short: Short) -> SeriesAssignment | None:
        active = self._get_active_series(session)
        if active is None:
            active = self._maybe_start_new_series(session, short.niche)
        if active is None:
            return None
        if short.niche != active.niche:
            short.niche = active.niche

        current_count = self._episode_count(session, active.id)
        if current_count >= active.planned_episodes:
            self._complete_series(active)
            session.commit()
            return None

        episode_no = current_count + 1
        link = SeriesEpisode(series_id=active.id, short_id=short.id, episode_number=episode_no)
        session.add(link)

        if episode_no >= active.planned_episodes:
            self._complete_series(active)

        session.commit()
        return SeriesAssignment(
            series_id=active.id,
            series_name=active.name,
            title_prefix=active.title_prefix,
            playlist_name=active.playlist_name,
            episode_number=episode_no,
            planned_episodes=active.planned_episodes,
        )

    def get_assignment_for_short(self, session, short_id: int) -> SeriesAssignment | None:
        row = (
            session.query(SeriesEpisode, StorySeries)
            .join(StorySeries, StorySeries.id == SeriesEpisode.series_id)
            .filter(SeriesEpisode.short_id == short_id)
            .first()
        )
        if not row:
            return None
        episode, series = row
        return SeriesAssignment(
            series_id=series.id,
            series_name=series.name,
            title_prefix=series.title_prefix,
            playlist_name=series.playlist_name,
            episode_number=episode.episode_number,
            planned_episodes=series.planned_episodes,
        )

    def get_series_continuity_context(self, session, series_id: int, episode_number: int) -> str:
        rows = (
            session.query(SeriesEpisode.episode_number, Short.title, Short.script)
            .join(Short, Short.id == SeriesEpisode.short_id)
            .filter(SeriesEpisode.series_id == series_id, SeriesEpisode.episode_number < episode_number)
            .order_by(SeriesEpisode.episode_number.asc())
            .all()
        )
        if not rows:
            return ""

        lines: list[str] = []
        for ep_no, title, script in rows[-3:]:
            story_preview = (script or "").strip().replace("\n", " ")
            if len(story_preview) > 260:
                story_preview = story_preview[:260].rsplit(" ", 1)[0] + "..."
            lines.append(f"EP{ep_no} TITLE: {title or ''}")
            lines.append(f"EP{ep_no} SUMMARY: {story_preview}")
        return "\n".join(lines)

    def ensure_playlist_id(self, session, series_id: int, playlist_id: str) -> None:
        series = session.query(StorySeries).filter(StorySeries.id == series_id).first()
        if series and not series.playlist_id:
            series.playlist_id = playlist_id
            session.commit()

    def get_playlist_id(self, session, series_id: int) -> str | None:
        series = session.query(StorySeries).filter(StorySeries.id == series_id).first()
        return series.playlist_id if series else None

    def _get_active_series(self, session) -> StorySeries | None:
        series = (
            session.query(StorySeries)
            .filter(StorySeries.status == SeriesStatus.ACTIVE)
            .order_by(StorySeries.started_at.desc(), StorySeries.id.desc())
            .first()
        )
        if not series:
            return None
        if self._episode_count(session, series.id) >= series.planned_episodes:
            self._complete_series(series)
            session.commit()
            return None
        return series

    def _maybe_start_new_series(self, session, niche: str) -> StorySeries | None:
        now = _utcnow_naive()

        name = self._series_name(now)
        series = StorySeries(
            name=name,
            niche=niche,
            title_prefix=name,
            playlist_name=f"{name} Series",
            planned_episodes=random.randint(*SERIES_EPISODE_RANGE),
            status=SeriesStatus.ACTIVE,
            started_at=now,
        )
        session.add(series)
        session.commit()
        session.refresh(series)
        return series

    def _series_name(self, when: datetime) -> str:
        season = f"S{when.isocalendar().week:02d}-{when.year % 100:02d}"
        return f"{random.choice(SERIES_NAME_WORDS_A)} {random.choice(SERIES_NAME_WORDS_B)} {season}"

    def _episode_count(self, session, series_id: int) -> int:
        return session.query(SeriesEpisode).filter(SeriesEpisode.series_id == series_id).count()

    def _complete_series(self, series: StorySeries) -> None:
        series.status = SeriesStatus.COMPLETED
        series.completed_at = _utcnow_naive()
