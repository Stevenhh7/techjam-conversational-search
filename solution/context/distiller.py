from __future__ import annotations

from solution.catalog import normalize_text
from solution.clarification import ALLOWED_ATTRIBUTES
from solution.context.schemas import DistilledContext, LongTermProfile, PreferenceEvidence
from solution.schemas import SessionState


def _session_evidence(state: SessionState) -> tuple[PreferenceEvidence, ...]:
    return tuple(
        PreferenceEvidence(
            attribute=item.attribute,
            value=item.value,
            polarity="positive",
            explicit=True,
            confidence=item.confidence,
            source_turn=item.source_turn,
            source_session=state.session_id,
            session_only=True,
            durable=False,
            updated_revision=state.state_revision,
        )
        for item in sorted(
            state.structured_constraints,
            key=lambda value: (value.attribute, value.value, value.source_turn),
        )
    )


class ContextDistiller:
    """Build a deterministic, bounded strategy context from session and profile state."""

    def __init__(
        self,
        max_messages: int = 4,
        max_candidates: int = 10,
        max_preferences: int = 16,
        max_summary_chars: int = 800,
        max_outcomes: int = 4,
    ) -> None:
        self.max_messages = max(1, max_messages)
        self.max_candidates = max(1, max_candidates)
        self.max_preferences = max(1, max_preferences)
        self.max_summary_chars = max(80, max_summary_chars)
        self.max_outcomes = max(1, max_outcomes)

    def distill(self, state: SessionState, profile: LongTermProfile) -> DistilledContext:
        session = _session_evidence(state)
        confirmed = tuple(item for item in session if any(
            value.attribute == item.attribute and value.value == item.value and value.hard
            for value in state.structured_constraints
        ))[: self.max_preferences]
        tentative = tuple(item for item in session if item not in confirmed)[: self.max_preferences]
        negative = tuple(
            PreferenceEvidence(
                attribute="exclusion",
                value=value,
                polarity="negative",
                explicit=True,
                confidence=0.95,
                source_turn=state.turn,
                source_session=state.session_id,
                session_only=True,
                durable=False,
                updated_revision=state.state_revision,
            )
            for value in sorted(state.exclusions)[: self.max_preferences]
        )
        active_attributes = {item.attribute for item in session}
        if state.category:
            active_attributes.add("category")
        durable = tuple(
            item
            for item in profile.preferences
            if item.durable and item.confidence >= 0.35
        )[: self.max_preferences]
        profile_conflicts = tuple(sorted({
            item.attribute
            for item in durable
            if item.attribute in active_attributes
            and any(
                current.attribute == item.attribute and current.value != item.value
                for current in session
            )
        }))
        unresolved = tuple(
            attribute
            for attribute in ALLOWED_ATTRIBUTES
            if attribute not in active_attributes
            and attribute not in state.unavailable_attributes
        )[:8]
        recent_override = state.last_override_turn > 0 or any(
            item.action in {"reset", "replace", "replace_value"}
            for item in state.slot_history[-4:]
        )
        outcomes = tuple(state.strategy_outcomes[-self.max_outcomes:])
        outcome_summaries = tuple(
            f"t{item.turn}:{item.program_track}:repeat={item.recommendation_repeat_rate:.2f}:"
            f"relaxed={len(item.relaxed_constraints)}:llm_failure={int(item.llm_failure)}"
            for item in outcomes
        )
        no_progress = 0
        for outcome in reversed(outcomes):
            if outcome.slot_acquired or outcome.override_detected or outcome.clarification_answered:
                break
            no_progress += 1
        consecutive_llm_failures = 0
        for outcome in reversed(outcomes):
            if not outcome.llm_failure:
                break
            consecutive_llm_failures += 1
        goal = normalize_text([state.category, state.hard_constraints, state.soft_preferences])
        messages = tuple(
            normalize_text(item)[:200] for item in state.message_history[-self.max_messages:]
        )
        parts = [
            f"goal={goal or 'open discovery'}",
            f"intent={state.intent}:{state.buying_probability:.2f}",
            "confirmed=" + ",".join(f"{item.attribute}:{item.value}" for item in confirmed),
            "tentative=" + ",".join(f"{item.attribute}:{item.value}" for item in tentative),
            "negative=" + ",".join(item.value for item in negative),
            "long_term=" + ",".join(f"{item.attribute}:{item.value}" for item in durable),
            "unresolved=" + ",".join(unresolved),
            f"override={int(recent_override)};no_progress={no_progress};llm_failures={consecutive_llm_failures}",
        ]
        summary = " | ".join(parts)[: self.max_summary_chars]
        return DistilledContext(
            core_goal=goal[:240],
            intent=state.intent,
            intent_confidence=round(max(state.buying_probability, 1.0 - state.buying_probability), 6),
            confirmed_preferences=confirmed,
            tentative_preferences=tentative,
            negative_preferences=negative,
            session_preferences=session[: self.max_preferences],
            long_term_preferences=durable,
            unresolved_attributes=unresolved,
            recent_override=recent_override,
            recommended_candidates=tuple(state.previous_recommendations[: self.max_candidates]),
            rejected_candidates=tuple(state.rejected_recommendations[-self.max_candidates:]),
            recent_strategy_outcomes=outcome_summaries,
            recent_messages=messages,
            profile_conflict_attributes=profile_conflicts,
            no_progress_turns=no_progress,
            consecutive_llm_failures=consecutive_llm_failures,
            summary=summary,
            context_revision=state.state_revision,
        )
