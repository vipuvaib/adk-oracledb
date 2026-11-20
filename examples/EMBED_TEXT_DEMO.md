# OCI embeddings from Google ADK Python

This example calls OCI Generative AI EmbedText using your private settings
at ~/.config/agno-oracle-demo/oci-iam.json. That file selects the
provider, embedding model ID, region, and compartment. Signing credentials stay
in ~/.oci/config; no credential values are stored in this source file.

The Agno demo's private config writer creates its config directory with mode
700 and its settings files with mode 600. The OCI profile also needs
use generative-ai-text-embedding access in the configured compartment.

## Install

    pip install oci google-adk

Run this helper in an environment with both private OCI configuration files.
Importing the module does not send a request; each embed_text call does.

## Call from ADK Python

Use the helper in an ingestion or retrieval function. Python ADK accepts a
plain Python function as a tool:

    from google.adk.agents import LlmAgent
    from examples.embed_text_demo import embed_text

    def search_documents(query: str) -> dict:
        query_vector = embed_text(query, input_type="SEARCH_QUERY")
        return vector_store.search(query_vector)  # use your vector store

    root_agent = LlmAgent(
        name="document_agent",
        model="gemini-flash-latest",
        instruction="Search the document collection when useful.",
        tools=[search_documents],
    )

For ingestion, call embed_text(chunk, input_type="SEARCH_DOCUMENT"), then
store the returned vector. For retrieval, use SEARCH_QUERY. Keep the same
model and output dimension for both sides of a vector search. The helper uses
the model's default output dimension; inspect len(vector) when configuring
the vector column or index.

## Request details

The helper reads the profile name, OCI config path, region, compartment, and
embedding model ID from the private config files. It sends one text in an
inputs list and uses truncate=NONE. OCI documents a maximum of 512 tokens per
text entry, so chunk longer documents before calling.

ADK's Python custom-function tool pattern is documented at
https://github.com/google/adk-docs/blob/main/docs/agents/llm-agents.md.
