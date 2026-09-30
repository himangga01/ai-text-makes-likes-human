export interface ShutdownSignalOptions {
  graceful(): void;
  force(): void;
  now?: () => number;
  repeatAfterMs?: number;
}

// npm and `tsx watch` forward the terminal's Ctrl-C to the server, which also
// receives it from the terminal, so one keypress arrives twice within
// milliseconds. Only a later repeat means the operator will not wait.
export function createShutdownSignalHandler(options: ShutdownSignalOptions): () => void {
  const now = options.now ?? Date.now;
  let firstAt: number | undefined;
  return () => {
    if (firstAt === undefined) {
      firstAt = now();
      options.graceful();
    } else if (now() - firstAt >= (options.repeatAfterMs ?? 1_000)) {
      options.force();
    }
  };
}
