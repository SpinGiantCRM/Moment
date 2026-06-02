"""Profile repository — edit profiles and game profiles."""

from __future__ import annotations

from moment.core.models import (
    EditProfile,
    FilterConfig,
    GameProfile,
    OverlayConfig,
    ReviewCardConfig,
    SegmentEdit,
)
from moment.core.repositories.base import BaseRepository, json_dumps, json_loads


class ProfileRepository(BaseRepository):
    """Persistence for edit profiles and game profiles."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    # ------------------------------------------------------------------
    # Edit profiles
    # ------------------------------------------------------------------

    def get_edit_profile(self, clip_id: str) -> EditProfile | None:
        row = self._read_conn.execute(
            "SELECT * FROM edit_profiles WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            return None
        return EditProfile(
            clip_id=row["clip_id"],
            trim_start=row["trim_start"],
            trim_end=row["trim_end"],
            split_points=json_loads(row["split_points"]) or [],
            segments=self._parse_segments(row["segments"]),
            game_audio_volume=row["game_audio_volume"],
            mic_audio_volume=row["mic_audio_volume"],
            filters=self._parse_filters(row["filters"]),
            overlays=self._parse_overlays(row["overlays"]),
            merge_source_ids=json_loads(row["merge_source_ids"]),
            edit_version=row["edit_version"],
        )

    def save_edit_profile(self, profile: EditProfile) -> EditProfile:
        row = {
            "clip_id": profile.clip_id,
            "trim_start": profile.trim_start,
            "trim_end": profile.trim_end,
            "split_points": json_dumps(profile.split_points),
            "segments": json_dumps([s.__dict__ for s in profile.segments]),
            "game_audio_volume": profile.game_audio_volume,
            "mic_audio_volume": profile.mic_audio_volume,
            "filters": json_dumps([f.__dict__ for f in profile.filters]),
            "overlays": json_dumps([o.__dict__ for o in profile.overlays]),
            "merge_source_ids": json_dumps(profile.merge_source_ids),
            "edit_version": profile.edit_version,
        }
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        with self.tx() as cur:
            cur.execute(
                f"INSERT OR REPLACE INTO edit_profiles ({columns}) VALUES ({placeholders})",  # nosec
                list(row.values()),
            )
        return profile

    # ------------------------------------------------------------------
    # Game profiles
    # ------------------------------------------------------------------

    def save_game_profile(self, profile: GameProfile) -> GameProfile:
        review_card_json = json_dumps(profile.review_card.__dict__) if profile.review_card else None
        with self.tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO game_profiles
                   (id, game_name, display_name, replay_duration, audio_config,
                    capture_fps, encode_timing, quality_preset, pause_encode,
                    pause_thumbnail, auto_tag, auto_open_editor, review_card,
                    min_duration, post_capture_action)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile.id,
                    profile.game_name,
                    profile.display_name,
                    profile.replay_duration,
                    json_dumps(profile.audio_config),
                    profile.capture_fps,
                    profile.encode_timing,
                    profile.quality_preset,
                    int(profile.pause_encode),
                    int(profile.pause_thumbnail),
                    int(profile.auto_tag),
                    int(profile.auto_open_editor),
                    review_card_json,
                    profile.min_duration,
                    profile.post_capture_action,
                ),
            )
        return profile

    def get_game_profile(self, game_name: str) -> GameProfile | None:
        """Return the profile for *game_name*, with case-insensitive lookup."""
        # Try exact match first, then case-insensitive fallback
        row = self._read_conn.execute(
            "SELECT * FROM game_profiles WHERE game_name = ?", (game_name,)
        ).fetchone()
        if row is None:
            row = self._read_conn.execute(
                "SELECT * FROM game_profiles WHERE LOWER(game_name) = LOWER(?)",
                (game_name,),
            ).fetchone()
        if row is None:
            return None
        review_card = None
        if row["review_card"]:
            rc_data = json_loads(row["review_card"])
            if isinstance(rc_data, dict):
                review_card = ReviewCardConfig(**rc_data)
        return GameProfile(
            id=row["id"],
            game_name=row["game_name"],
            display_name=row["display_name"],
            replay_duration=row["replay_duration"],
            audio_config=json_loads(row["audio_config"]),
            capture_fps=row["capture_fps"],
            encode_timing=row["encode_timing"],
            quality_preset=row["quality_preset"],
            pause_encode=bool(row["pause_encode"]),
            pause_thumbnail=bool(row["pause_thumbnail"]),
            auto_tag=bool(row["auto_tag"]),
            auto_open_editor=bool(row["auto_open_editor"]),
            review_card=review_card,
            min_duration=row["min_duration"],
            post_capture_action=row["post_capture_action"] or "card",
        )

    def list_game_profiles(self, limit: int = 100, offset: int = 0) -> list[GameProfile]:
        rows = self._read_conn.execute(
            "SELECT * FROM game_profiles LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        profiles: list[GameProfile] = []
        for r in rows:
            review_card = None
            if r["review_card"]:
                rc_data = json_loads(r["review_card"])
                if isinstance(rc_data, dict):
                    review_card = ReviewCardConfig(**rc_data)
            profiles.append(
                GameProfile(
                    id=r["id"],
                    game_name=r["game_name"],
                    display_name=r["display_name"],
                    replay_duration=r["replay_duration"],
                    audio_config=json_loads(r["audio_config"]),
                    capture_fps=r["capture_fps"],
                    encode_timing=r["encode_timing"],
                    quality_preset=r["quality_preset"],
                    pause_encode=bool(r["pause_encode"]),
                    pause_thumbnail=bool(r["pause_thumbnail"]),
                    auto_tag=bool(r["auto_tag"]),
                    auto_open_editor=bool(r["auto_open_editor"]),
                    review_card=review_card,
                    min_duration=r["min_duration"],
                    post_capture_action=r["post_capture_action"] or "card",
                )
            )
        return profiles

    def delete_game_profile(self, game_name: str) -> None:
        """Remove the profile for *game_name* (case-insensitive, no-op if not found)."""
        with self.tx() as cur:
            cur.execute(
                "DELETE FROM game_profiles WHERE LOWER(game_name) = LOWER(?)",
                (game_name,),
            )

    # ------------------------------------------------------------------
    # Helpers for deserializing complex edit types
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_segments(raw: str | None) -> list[SegmentEdit]:
        data = json_loads(raw) or []
        return [SegmentEdit(**s) for s in data if isinstance(s, dict)]

    @staticmethod
    def _parse_filters(raw: str | None) -> list[FilterConfig]:
        data = json_loads(raw) or []
        return [FilterConfig(**f) for f in data if isinstance(f, dict)]

    @staticmethod
    def _parse_overlays(raw: str | None) -> list[OverlayConfig]:
        data = json_loads(raw) or []
        return [OverlayConfig(**o) for o in data if isinstance(o, dict)]
