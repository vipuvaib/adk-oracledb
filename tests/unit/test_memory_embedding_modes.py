"""OCI query/document embedding modes must reach the selected provider."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from adk_oracledb.memory import OracleMemoryService, OracleMemoryServiceConfig


class MemoryEmbeddingModesTest(unittest.IsolatedAsyncioTestCase):
  async def test_query_and_document_modes_reach_the_correct_embedder(self):
    seen = []

    class RecordingEmbedder:
      def __init__(self, model, *, api_base=None, api_key=None, embedding_kwargs=None):
        self.mode = embedding_kwargs["input_type"]

      def embed(self, texts, *, is_query=False):
        seen.append((self.mode, tuple(texts), is_query))
        return self.mode

      async def embed_async(self, texts, *, is_query=False):
        return self.embed(texts, is_query=is_query)

    service = OracleMemoryService(OracleMemoryServiceConfig(
        user="test", password="test", dsn="test", embedder_model="oci/cohere.embed-v4.0",
        embedder_query_input_type=" SEARCH_QUERY ",
        embedder_document_input_type="SEARCH_DOCUMENT",
    ))
    embedder = service._build_embedder(RecordingEmbedder)
    self.assertEqual(embedder.embed(["stored fact"]), "search_document")
    self.assertEqual(await embedder.embed_async(["paraphrased question"], is_query=True), "search_query")
    self.assertEqual(seen, [
        ("search_document", ("stored fact",), False),
        ("search_query", ("paraphrased question",), True),
    ])

  def test_provider_options_work_with_the_pinned_memory_embedder(self):
    from oracleagentmemory.core.embedders.embedder import Embedder

    service = OracleMemoryService(OracleMemoryServiceConfig(
        user="test", password="test", dsn="test",
        embedder_model="oci/cohere.embed-v4.0",
        embedder_input_type="search_document", embedder_encoding_format="float",
    ))
    # Construction must accept provider options without sending any request.
    embedder = service._build_embedder(Embedder)
    self.assertEqual(embedder._embedding_kwargs["input_type"], "search_document")
    self.assertEqual(embedder._embedding_kwargs["encoding_format"], "float")

  def test_misspelled_provider_mode_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "embedder_input_type"):
      OracleMemoryServiceConfig(
          user="test", password="test", dsn="test",
          embedder_query_input_type="search_queri",
      )


if __name__ == "__main__":
  unittest.main()
