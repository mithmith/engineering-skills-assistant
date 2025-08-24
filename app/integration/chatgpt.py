"""OpenAI client integration utilities."""
from __future__ import annotations

from typing import Any

from openai import OpenAI
from app.config import settings


class OpenAIClient:
    def __init__(
        self,
        api_key: str = settings.openai_api_key,
        model_name: str = settings.model_name,
    ) -> None:
        self.model_name = model_name
        self._client = OpenAI(api_key=api_key)

    def create(self, input_data: Any, **kwargs):
        """
        Thin wrapper over Responses API with passthrough kwargs, e.g.:
          - store=True
          - previous_response_id="..."
        """
        model = kwargs.pop("model", self.model_name)
        return self._client.responses.create(
            model=model,
            input=input_data,
            **kwargs,
        )
