import { describe, expect, it } from "vitest";
import { CodexSemaphore } from "../../src/engine/codex-semaphore.js";
import { deferred } from "../helpers/deferred.js";

describe("CodexSemaphore", () => {
  it("does not start a third task before either of two permits is released", async () => {
    const semaphore = new CodexSemaphore(2);
    const started = [deferred<void>(), deferred<void>(), deferred<void>()];
    const releases = [deferred<void>(), deferred<void>(), deferred<void>()];
    let active = 0;
    let maxActive = 0;

    const tasks = releases.map((release, index) =>
      semaphore.run(new AbortController().signal, async () => {
        active += 1;
        maxActive = Math.max(maxActive, active);
        started[index]!.resolve();
        try {
          await release.promise;
        } finally {
          active -= 1;
        }
      })
    );

    await Promise.all([started[0]!.promise, started[1]!.promise]);
    expect(active).toBe(2);
    expect(maxActive).toBe(2);
    expect(semaphore.maxObserved).toBe(2);

    releases[0]!.resolve();
    await started[2]!.promise;
    expect(maxActive).toBe(2);

    releases[1]!.resolve();
    releases[2]!.resolve();
    await Promise.all(tasks);
    expect(active).toBe(0);
    expect(semaphore.maxObserved).toBe(2);
  });

  it("removes an aborted waiter and never invokes its callback", async () => {
    const semaphore = new CodexSemaphore(1);
    const firstStarted = deferred<void>();
    const firstRelease = deferred<void>();
    const abortedController = new AbortController();
    const thirdStarted = deferred<void>();
    let abortedTaskRan = false;

    const first = semaphore.run(new AbortController().signal, async () => {
      firstStarted.resolve();
      await firstRelease.promise;
    });
    await firstStarted.promise;

    const aborted = semaphore.run(abortedController.signal, async () => {
      abortedTaskRan = true;
    });
    const third = semaphore.run(new AbortController().signal, async () => {
      thirdStarted.resolve();
    });

    abortedController.abort();
    await expect(aborted).rejects.toMatchObject({
      publicCode: "CLIENT_ABORTED"
    });
    expect(abortedTaskRan).toBe(false);

    firstRelease.resolve();
    await thirdStarted.promise;
    await Promise.all([first, third]);
    expect(abortedTaskRan).toBe(false);
    expect(semaphore.maxObserved).toBe(1);
  });

  it("releases exactly one permit when a task throws", async () => {
    const semaphore = new CodexSemaphore(1);
    const failure = new Error("worker failed");
    const firstStarted = deferred<void>();
    const firstRelease = deferred<void>();
    const secondStarted = deferred<void>();
    const secondRelease = deferred<void>();
    const thirdStarted = deferred<void>();
    const probeStarted = deferred<void>();
    let thirdRan = false;
    let secondReleased = false;
    let probeRanBeforeSecondRelease = false;

    const first = semaphore.run(new AbortController().signal, async () => {
      firstStarted.resolve();
      await firstRelease.promise;
      throw failure;
    });
    await firstStarted.promise;

    const second = semaphore.run(new AbortController().signal, async () => {
      secondStarted.resolve();
      await secondRelease.promise;
    });
    const third = semaphore.run(new AbortController().signal, async () => {
      thirdRan = true;
      thirdStarted.resolve();
    });

    firstRelease.resolve();
    await expect(first).rejects.toBe(failure);
    await secondStarted.promise;
    expect(thirdRan).toBe(false);

    const probe = semaphore.run(new AbortController().signal, async () => {
      probeRanBeforeSecondRelease = !secondReleased;
      probeStarted.resolve();
    });
    const checkpoint = deferred<void>();
    queueMicrotask(() => checkpoint.resolve());
    await checkpoint.promise;

    secondReleased = true;
    secondRelease.resolve();
    await thirdStarted.promise;
    await probeStarted.promise;
    await Promise.all([second, third, probe]);
    expect(probeRanBeforeSecondRelease).toBe(false);
    expect(semaphore.maxObserved).toBe(1);
  });

  it.each([0, -1, 1.5, Number.NaN])(
    "rejects invalid capacity %s",
    capacity => {
      expect(() => new CodexSemaphore(capacity)).toThrow(
        "Codex semaphore capacity must be a positive integer"
      );
    }
  );
});
