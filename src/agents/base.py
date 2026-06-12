"""Base agent class for the multi-agent analysis pipeline."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime


class BaseAgent(ABC):
    """Abstract base for all analysis agents.

    Each agent receives a shared state dict, performs its analysis,
    writes results to a namespaced key, and returns the state.
    Agents are pure readers — they never write to the database.
    """

    def __init__(self, conn, config: dict) -> None:
        self._conn = conn
        self._config = config
        self._logger = logging.getLogger(self.__class__.__module__)

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier string."""
        ...

    @abstractmethod
    def run(self, state: dict) -> dict:
        """Execute analysis, mutate state, return the state dict.

        Parameters
        ----------
        state : dict
            Shared pipeline state. Agents read inputs from here and
            write their output to a namespaced key.

        Returns
        -------
        dict
            The same state dict (for convenience).
        """
        ...

    def _timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
