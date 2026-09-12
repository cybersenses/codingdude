# 16: Embeddings

**What to build:** Semantic retrieval where keywords fail: embeddings-based code search across the Workdir, and an upgrade of Memory retrieval from keyword+recency to relevance.

**Blocked by:** 11 (Memory store), 15 (AST tools)

**Status:** resolved — semantic search + memory relevance upgrade shipped

- [x] Semantic code search finds code that grep misses in a sample repo (different vocabulary, same concept)
- [x] Memory retrieval by relevance beats pure recency in a scripted comparison case
- [x] The embedder is configurable (provider/model) via the same config system as the model lineup

2026-09-08: Resolved. Commit d4593c7. Embedder is injectable (`.embed(text) -> vector`); `FakeEmbedder` (deterministic trigram hashing, offline) proves the pipeline in tests; production wires a provider embedder the same way — set it at Engine construction (`embedder=`). `SemanticIndex` embeds Workdir files (code + doc extensions, size-capped) into SQLite with content-hash caching so unchanged files never re-embed. Exposed as the `semantic_search` tool for the model, and Memory retrieval upgrades from keyword+recency to similarity when an embedder is present. Semantic search naturally finds concept matches text-grep misses (tested: "delays after a failed operation" → backoff/retry code).
