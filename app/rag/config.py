import os

TOP_K = int(os.getenv("RAG_TOP_K", "5"))
CHUNK_MAX_CHARS = int(os.getenv("RAG_CHUNK_MAX_CHARS", "2000"))
CHUNK_SELECTION_ENABLED: bool = (
    os.getenv("RAG_CHUNK_SELECTION_ENABLED", "false").lower() == "true"
)

# Oversample factor per retrieval leg before RRF fusion.
# Each leg fetches TOP_K * FUSION_OVERSAMPLE_FACTOR candidates to ensure
# cross-leg candidates aren't cut off before ranking. See: Cormack et al. (2009).
FUSION_OVERSAMPLE_FACTOR: int = 4
