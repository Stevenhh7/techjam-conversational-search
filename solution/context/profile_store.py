from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from solution.context.schemas import LongTermProfile, PreferenceEvidence, ProfileMutation


class ProfileStore(Protocol):
    def load(self, profile_id: str) -> LongTermProfile: ...

    def update(self, profile_id: str, mutations: tuple[ProfileMutation, ...]) -> LongTermProfile: ...

    def delete(self, profile_id: str) -> None: ...


class InMemoryProfileStore:
    """Process-local profile store requiring an explicit stable anonymous profile ID."""

    def __init__(self, promotion_sessions: int = 2, decay: float = 0.98) -> None:
        self.promotion_sessions = max(2, promotion_sessions)
        self.decay = max(0.0, min(1.0, decay))
        self._profiles: dict[str, LongTermProfile] = {}
        self._observations: dict[tuple[str, str, str], set[str]] = {}

    @staticmethod
    def _clean_profile_id(profile_id: str) -> str:
        return str(profile_id).strip()[:128]

    def load(self, profile_id: str) -> LongTermProfile:
        key = self._clean_profile_id(profile_id)
        if not key:
            return LongTermProfile("")
        return self._profiles.get(key, LongTermProfile(key))

    def update(self, profile_id: str, mutations: tuple[ProfileMutation, ...]) -> LongTermProfile:
        key = self._clean_profile_id(profile_id)
        if not key:
            return LongTermProfile("")
        profile = self._profiles.get(key, LongTermProfile(key))
        preferences = {
            (item.attribute, item.value): replace(
                item,
                confidence=round(item.confidence * self.decay, 6),
            )
            for item in profile.preferences
            if item.confidence * self.decay >= 0.35
        }
        changed = tuple(preferences.values()) != profile.preferences
        for mutation in mutations:
            attribute = mutation.attribute.strip().lower()[:64]
            value = mutation.value.strip().lower()[:160]
            if not attribute:
                continue
            if mutation.action == "forget":
                if attribute == "*":
                    preferences.clear()
                    for observation_key in [item for item in self._observations if item[0] == key]:
                        del self._observations[observation_key]
                    changed = True
                    continue
                targets = [
                    item_key
                    for item_key in preferences
                    if item_key[0] == attribute and (not value or item_key[1] == value)
                ]
                for item_key in targets:
                    del preferences[item_key]
                    self._observations.pop((key, *item_key), None)
                    changed = True
                continue
            if not value or mutation.action not in {"observe", "remember"}:
                continue
            observation_key = (key, attribute, value)
            sessions = self._observations.setdefault(observation_key, set())
            if mutation.source_session:
                sessions.add(mutation.source_session)
            durable = mutation.action == "remember" or len(sessions) >= self.promotion_sessions
            if not durable:
                continue
            old = preferences.get((attribute, value))
            confirmations = max(len(sessions), old.confirmations if old else 1)
            confidence = max(mutation.confidence, old.confidence if old else 0.0)
            preferences[(attribute, value)] = PreferenceEvidence(
                attribute=attribute,
                value=value,
                polarity="positive",
                explicit=mutation.action == "remember",
                confidence=round(min(1.0, confidence), 6),
                source_turn=mutation.source_turn,
                source_session=mutation.source_session,
                session_only=False,
                durable=True,
                updated_revision=profile.revision + 1,
                confirmations=confirmations,
            )
            changed = changed or old != preferences[(attribute, value)]
        if changed:
            ordered = tuple(sorted(preferences.values(), key=lambda item: (item.attribute, item.value)))
            profile = LongTermProfile(key, profile.summary, ordered, profile.revision + 1)
            self._profiles[key] = profile
        return profile

    def delete(self, profile_id: str) -> None:
        key = self._clean_profile_id(profile_id)
        self._profiles.pop(key, None)
        for observation_key in [item for item in self._observations if item[0] == key]:
            del self._observations[observation_key]
