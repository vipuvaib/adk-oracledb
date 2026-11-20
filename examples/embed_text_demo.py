"""OCI EmbedText helper for Google ADK Python code.

The helper reads the user's private configuration and OCI SDK profile.
It makes no request until embed_text() is called.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import oci


InputType = Literal["SEARCH_DOCUMENT", "SEARCH_QUERY"]
SETTINGS_PATH = (
    Path.home() / ".config" / "agno-oracle-demo" / "oci-iam.json"
)


class OciTextEmbedder:
    """Call OCI Generative AI EmbedText using the saved OCI IAM profile."""

    def __init__(self) -> None:
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Could not read OCI demo settings at {SETTINGS_PATH}"
            ) from exc

        embedding = settings.get("embedding") or {}
        if embedding.get("provider") != "oci":
            raise RuntimeError(
                "Set embedding.provider to 'oci' in oci-iam.json."
            )

        self.model_id = embedding.get("model_id")
        self.region = embedding.get("region") or settings.get("region")
        self.compartment_id = settings.get("compartment_id")
        profile_name = settings.get("profile_name", "DEFAULT")
        config_file = Path(
            settings.get("config_file", "~/.oci/config")
        ).expanduser()

        if not self.model_id or not self.region or not self.compartment_id:
            raise RuntimeError(
                "oci-iam.json needs embedding.model_id, a region, "
                "and compartment_id."
            )

        oci_config = oci.config.from_file(str(config_file), profile_name)
        # The endpoint and request signer must use the same OCI region.
        oci_config["region"] = self.region
        endpoint = (
            f"https://inference.generativeai.{self.region}.oci.oraclecloud.com"
        )
        self.client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            config=oci_config,
            service_endpoint=endpoint,
            retry_strategy=oci.retry.NoneRetryStrategy(),
            timeout=(10, 240),
        )

    def embed_text(
        self,
        text: str,
        *,
        input_type: InputType = "SEARCH_DOCUMENT",
    ) -> list[float]:
        """Return one float vector for a document or search query."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a nonempty string")

        details = oci.generative_ai_inference.models.EmbedTextDetails(
            inputs=[text],
            serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                model_id=self.model_id
            ),
            compartment_id=self.compartment_id,
            truncate="NONE",
            input_type=input_type,
        )
        response = self.client.embed_text(details)
        embeddings = response.data.embeddings
        if not embeddings or not embeddings[0]:
            raise RuntimeError("OCI returned no embedding for the input")
        return [float(value) for value in embeddings[0]]


_default_embedder: OciTextEmbedder | None = None


def embed_text(
    text: str,
    *,
    input_type: InputType = "SEARCH_DOCUMENT",
) -> list[float]:
    """Embed text using the configured OCI model; safe to import in an ADK app."""
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = OciTextEmbedder()
    return _default_embedder.embed_text(text, input_type=input_type)
