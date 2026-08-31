"""Official-evaluator adapter for the final ContextCart submission.

The organizer harness imports ``starter.agent:Agent``. Keeping this file as a
thin adapter makes the default evaluator command exercise the submitted agent
without changing the evaluator itself. The original weak BM25 starter remains
available as ``starter.baseline_agent:Agent`` for baseline reproduction.
"""

from solution.agent import Agent

__all__ = ["Agent"]
