"""Deadline-budgeted fan-out over agents with independent failure modes."""

from .case import CaseFile, case_id_for
from .contract import Agent, AgentResult, deadline_budget, guarded
from .orchestrate import adjudicate, dispatch, run_case

__all__ = [
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
