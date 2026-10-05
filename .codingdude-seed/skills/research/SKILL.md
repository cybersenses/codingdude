{"name": "research", "description": "Investigate a question against high-trust primary sources and capture the findings as a Markdown file in the repo. Use when the user wants a topic researched, docs or API facts gathered, or reading legwork delegated to a background agent.", "triggers": ["research", "investigate", "look into", "find out how", "compare options for"]}

Delegate the reading to a **sub-agent with the `delegate` tool** (pass `write=false` for read-only investigation; it reports findings back), so your own context stays clean while it works.

Its job:

1. Investigate the question against **primary sources** (official docs, source code, specs, first-party APIs), not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Save it where the repo already keeps such notes; match the existing convention, and if there is none, put it somewhere sensible and say where.
