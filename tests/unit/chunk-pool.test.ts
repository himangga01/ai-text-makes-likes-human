import { describe, expect, it } from "vitest";
import { runChunkPool } from "../../src/engine/chunk-pool.js";
import { deferred } from "../helpers/deferred.js";

describe("runChunkPool", () => {
  it("limits workers to two and returns results in input order", async () => {
    const started = [
      deferred<void>(),
      deferred<void>(),
      deferred<void>(),
      deferred<void>()
    ];
    const releases = [
      deferred<void>(),
      deferred<void>(),
      deferred<void>(),
      deferred<void>()
    ];
    const words = ["one", "two", "three", "four"] as const;
    let active = 0;
    let maxActive = 0;

    const resultPromise = runChunkPool(
      [1, 2, 3, 4],
      2,
      new AbortController().signal,
      async item => {
        active += 1;
        maxActive = Math.max(maxActive, active);
        started[item - 1]!.resolve();
        try {
          await releases[item - 1]!.promise;
          return words[item - 1]!;
        } finally {
          active -= 1;
        }
      }
    );

    await Promise.all([started[0]!.promise, started[1]!.promise]);
    expect(active).toBe(2);

    releases[1]!.resolve();
    await started[2]!.promise;
    releases[0]!.resolve();
    await started[3]!.promise;
    releases[3]!.resolve();
    releases[2]!.resolve();

    await expect(resultPromise).resolves.toEqual([
      "one",
      "two",
      "three",
      "four"
    ]);
    expect(maxActive).toBe(2);
    expect(active).toBe(0);
  });

  it("aborts siblings on first failure and waits for active siblings to settle", async () => {
    const firstStarted = deferred<void>();
    const secondStarted = deferred<void>();
    const secondFailure = deferred<never>();
    const firstObservedAbort = deferred<void>();
    const firstMaySettle = deferred<void>();
    const failure = new Error("second worker failed");
    const startedItems: number[] = [];
    let poolSettled = false;

    const poolPromise = runChunkPool(
      [1, 2, 3, 4],
      2,
      new AbortController().signal,
      async (item, signal) => {
        startedItems.push(item);
        if (item === 1) {
          firstStarted.resolve();
          await new Promise<void>(resolve => {
            const observe = (): void => {
              firstObservedAbort.resolve();
              resolve();
            };
            if (signal.aborted) observe();
            else signal.addEventListener("abort", observe, { once: true });
          });
          await firstMaySettle.promise;
          return "one";
        }
        if (item === 2) {
          secondStarted.resolve();
          await secondFailure.promise;
        }
        throw new Error(`unexpected worker ${item}`);
      }
    );
    const observedPool = poolPromise.then(
      value => {
        poolSettled = true;
        return { status: "fulfilled" as const, value };
      },
      error => {
        poolSettled = true;
        return { status: "rejected" as const, error: error as unknown };
      }
    );

    await Promise.all([firstStarted.promise, secondStarted.promise]);
    secondFailure.reject(failure);
    await firstObservedAbort.promise;

    expect(startedItems).toEqual([1, 2]);
    expect(poolSettled).toBe(false);

    firstMaySettle.resolve();
    await expect(observedPool).resolves.toEqual({
      status: "rejected",
      error: failure
    });
    expect(startedItems).toEqual([1, 2]);
  });

  it("maps parent cancellation to the public client-aborted error", async () => {
    const parent = new AbortController();
    const started = deferred<void>();
    const observedAbort = deferred<void>();
    const poolPromise = runChunkPool([1], 1, parent.signal, async (_item, signal) => {
      started.resolve();
      await new Promise<void>(resolve => {
        const observe = (): void => {
          observedAbort.resolve();
          resolve();
        };
        if (signal.aborted) observe();
        else signal.addEventListener("abort", observe, { once: true });
      });
      return "ignored";
    });

    await started.promise;
    parent.abort();
    await observedAbort.promise;

    await expect(poolPromise).rejects.toMatchObject({
      publicCode: "CLIENT_ABORTED"
    });
  });

  it.each([0, -1, 1.5, Number.NaN])(
    "rejects invalid concurrency %s before a worker starts",
    async concurrency => {
      let starts = 0;

      await expect(
        runChunkPool(
          [1],
          concurrency,
          new AbortController().signal,
          async () => {
            starts += 1;
            return "one";
          }
        )
      ).rejects.toThrow("Chunk concurrency must be a positive integer");
      expect(starts).toBe(0);
    }
  );
});
