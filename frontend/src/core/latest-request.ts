// Author: Ching Kao
// Student ID: 85768427
/** Owns one replaceable read request; callers must check isCurrent after awaits. */
export function latestRequest() {
  let controller: AbortController | undefined;
  return {
    start() {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      return {
        signal: current.signal,
        isCurrent: () => controller === current && !current.signal.aborted,
      };
    },
    cancel() {
      controller?.abort();
      controller = undefined;
    },
  };
}
