"""Internal validation helpers for credential-bearing service settings."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError


def _validate_without_input_values(value: Any, handler: Any) -> Any:
  """Keep raw configuration inputs out of text and structured error output."""
  try:
    return handler(value)
  except ValidationError as error:
    # hide_input_in_errors only affects text; errors()/json() include inputs too.
    details = [
        {key: item for key, item in detail.items() if key in {"type", "loc", "ctx"}}
        for detail in error.errors(include_input=False)
    ]
    raise ValidationError.from_exception_data(
        error.title, details, hide_input=True
    ) from None
