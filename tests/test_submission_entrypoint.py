from __future__ import annotations

import unittest

from agent import Agent as SubmissionAgent
from solution.agent import Agent as SolutionAgent
from starter.agent import Agent as EvaluatorDefaultAgent


class SubmissionEntrypointTests(unittest.TestCase):
    def test_all_public_entrypoints_resolve_to_the_final_agent(self) -> None:
        self.assertIs(SubmissionAgent, SolutionAgent)
        self.assertIs(EvaluatorDefaultAgent, SolutionAgent)


if __name__ == "__main__":
    unittest.main()
