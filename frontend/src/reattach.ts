// R29 (#58): decide whether the UI should reattach to a live run's SSE stream
// on boot/refresh — the selected session has a live run and we are not
// already attached to one.

export function runToReattach(
  liveRuns: Map<string, string>,
  activeSession: string | null,
  attachedRun: string | null,
): string | null {
  if (!activeSession || attachedRun) return null
  return liveRuns.get(activeSession) ?? null
}
