# 16: Embeddings

**What to build:** Semantic retrieval where keywords fail: embeddings-based code search across the Workdir, and an upgrade of Memory retrieval from keyword+recency to relevance.

**Blocked by:** 11 (Memory store), 15 (AST tools)

**Status:** ready-for-agent

- [ ] Semantic code search finds code that grep misses in a sample repo (different vocabulary, same concept)
- [ ] Memory retrieval by relevance beats pure recency in a scripted comparison case
- [ ] The embedder is configurable (provider/model) via the same config system as the model lineup
