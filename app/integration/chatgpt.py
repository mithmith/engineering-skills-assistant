"""OpenAI client integration utilities.

This module provides a small wrapper around the official ``openai``
client so the rest of the project can interact with the Responses API
without dealing with low level configuration details.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.config import settings


class OpenAIClient:
    """Convenience wrapper for the OpenAI Responses API."""

    def __init__(
        self,
        api_key: str = settings.openai_api_key,
        model_name: str = settings.model_name,
    ) -> None:
        self.model_name = model_name
        # ``OpenAI`` reads the key from the environment if ``api_key`` is ``None``.
        # Passing it explicitly keeps the behaviour predictable.
        self._client = OpenAI(api_key=api_key)

    def create(self, input_data: Any):
        """Send ``input_data`` to the Responses API.

        Parameters
        ----------
        input_data:
            Either a plain string prompt or a list of messages compatible with
            the Responses API.
        """

        return self._client.responses.create(
            model=self.model_name,
            input=input_data,
        )

    # Removed deprecated run_prompt_file utility to simplify integration surface.
