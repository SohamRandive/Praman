"""Deadline-budgeted fan-out over agents with independent failure modes."""

from .case import CaseFile, case_id_for
from .contract import Agent, AgentResult, deadline_budget, guarded
from .orchestrate import adjudicate, dispatch, draft_if_contesting, run_case

__all__ = [
    "draft_if_contesting",
    "Agent",
    "AgentResult",
    "CaseFile",
    "adjudicate",
    "case_id_for",
    "deadline_budget",
    "dispatch",
    "guarded",
    "run_case",
]
