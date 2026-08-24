import { EngineError } from "./errors.js";

function clientAbortedError(): EngineError {
  return new EngineError("CLIENT_ABORTED", true, "Chunk pool cancelled");
}

export async function runChunkPool<T, R>(
  items: readonly T[],
  concurrency: number,
  parentSignal: AbortSignal,
  worker: (item: T, signal: AbortSignal) => Promise<R>
): Promise<R[]> {
  if (!Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error("Chunk concurrency must be a positive integer");
  }
  const failure = new AbortController();
  const signal = AbortSignal.any([parentSignal, failure.signal]);
  const results = new Array<R>(items.length);
  let cursor = 0;
  let hasFirstError = false;
  let firstError: unknown;

  const runWorker = async (): Promise<void> => {
    while (!signal.aborted) {
      const index = cursor++;
      if (index >= items.length) return;
      try {
        results[index] = await worker(items[index]!, signal);
      } catch (error) {
        if (!parentSignal.aborted && !hasFirstError) {
          hasFirstError = true;
          firstError = error;
          failure.abort();
        }
        return;
      }
    }
  };

  await Promise.allSettled(
    Array.from({ length: Math.min(concurrency, items.length) }, runWorker)
  );
  if (hasFirstError) throw firstError;
  if (parentSignal.aborted) throw clientAbortedError();
  return results;
}
