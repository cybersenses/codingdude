# 09: React shell

**What to build:** The browser face of CodingDude (ADR-0001): a React + Vite + Tailwind app speaking the AG-UI client protocol over SSE. The session sidebar creates Sessions per Workdir and lists/resumes past ones; the center pane streams the chat with a collapsible inline tool-call timeline (args → output → duration); a run can be stopped.

**Blocked by:** 08 (Web server + worker + SSE)

**Status:** ready-for-agent

- [ ] Browser: create a Session on a Workdir, send a prompt, watch the streamed reply
- [ ] Tool calls appear as collapsible timeline entries with arguments, output, and duration
- [ ] Sidebar lists past Sessions and resumes one with its history rendered
- [ ] Stop button cancels a running run
- [ ] Dev build proxies to the local server without manual URL fiddling
