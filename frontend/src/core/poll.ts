/** No overlap, and no retry can be scheduled after stop, even during an await. */
export function startPolling(
  read: (signal: AbortSignal) => Promise<void>,
  onError: (error: unknown) => void,
  interval = 3000,
) {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  async function tick() {
    try {
      await read(controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) onError(error);
    } finally {
      if (!controller.signal.aborted)
        timer = setTimeout(() => {
          void tick();
        }, interval);
    }
  }
  void tick();
  return () => {
    controller.abort();
    clearTimeout(timer);
  };
}
