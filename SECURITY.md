# Security Policy

## Supported versions

Only the latest `main` branch receives security fixes.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Email **security@cyberflex.io** with:

- a description of the issue and its impact,
- reproduction steps or a proof of concept,
- affected version/commit.

You will receive an acknowledgement within 7 days. Please avoid public
disclosure until a fix is released; we will credit reporters who wish to
be acknowledged.

## Scope notes

- CodingDude is a **single-user, local-first** tool: the web server binds
  to localhost and expects a trusted operator. Issues that require the
  operator attacking their own machine are generally out of scope.
- Report handling of **API keys**: keys live in `~/.codingdude/config.toml`
  or environment variables and are never returned by the API (masked
  sentinels only). Any path that leaks key material is in scope and
  treated with priority.
