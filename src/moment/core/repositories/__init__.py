"""Domain-specific repositories for Moment persistence.

Store is a backward-compatible facade that delegates to these repos.
"""

from __future__ import annotations

from moment.core.repositories.base import BaseRepository
from moment.core.repositories.bookmark_repo import BookmarkRepository
from moment.core.repositories.clip_repo import ClipRepository
from moment.core.repositories.folder_repo import FolderRepository
from moment.core.repositories.profile_repo import ProfileRepository
from moment.core.repositories.settings_repo import SettingsRepository
from moment.core.repositories.tag_repo import TagRepository
from moment.core.repositories.task_repo import TaskRepository
from moment.core.repositories.webhook_repo import WebhookRepository

__all__ = [
    "BaseRepository",
    "ClipRepository",
    "WebhookRepository",
    "ProfileRepository",
    "TagRepository",
    "TaskRepository",
    "FolderRepository",
    "BookmarkRepository",
    "SettingsRepository",
]
