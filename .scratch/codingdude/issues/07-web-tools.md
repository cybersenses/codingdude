# 07: Web tools

**What to build:** CodingDude can search the web and read pages without leaving the run loop, using pydantic-ai's built-in DuckDuckGo search and web-fetch tools — no API keys.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] The agent's toolset includes web search and page fetch
- [x] A scripted run fetches content from a stubbed local URL and quotes it
- [x] No API key or account is required for either tool

## Comments

2026-09-07: Commits 4e354ad + 6a60ce7. Built-ins attached by default on every run; DDG search renamed to `web_search` via RenamedToolset for spec-consistent naming. web_fetch runs with allow_local_urls=True (tests, self-hosted docs). New deps: ddgs, markdownify.
