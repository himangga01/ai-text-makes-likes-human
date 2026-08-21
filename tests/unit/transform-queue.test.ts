import { describe, expect, it } from "vitest";
import { TransformQueue } from "../../src/queue/transform-queue.js";
import { deferred } from "../helpers/deferred.js";

describe("TransformQueue", () => {
  it("runs one job, queues two in FIFO order, and rejects a fourth", async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
    const first = queue.reserve("a")!;
    const second = queue.reserve("b")!;
    const third = queue.reserve("c")!;
    expect(queue.reserve("d")).toBeNull();
    expect(queue.stats()).toEqual({ active: 0, queued: 0, reserved: 3 });

    const firstGate = deferred<void>();
    const order: string[] = [];
    const secondPositions: number[] = [];
    const thirdPositions: number[] = [];
    const firstPromise = first.submit(async () => {
      order.push("a");
      await firstGate.promise;
    }, () => undefined);
    const secondPromise = second.submit(async () => {
      order.push("b");
    }, position => secondPositions.push(position));
    const thirdPromise = third.submit(async () => {
      order.push("c");
    }, position => thirdPositions.push(position));

    expect(queue.stats()).toEqual({ active: 1, queued: 2, reserved: 0 });
    expect(secondPositions.at(-1)).toBe(1);
    expect(thirdPositions.at(-1)).toBe(2);
    firstGate.resolve();
    await Promise.all([firstPromise, secondPromise, thirdPromise]);

    expect(order).toEqual(["a", "b", "c"]);
    expect(queue.stats()).toEqual({ active: 0, queued: 0, reserved: 0 });
  });

  it("releases an upload reservation and makes capacity available", () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 1 });
    const reservation = queue.reserve("upload")!;
    expect(queue.reserve("blocked")).toBeNull();

    reservation.release();
    reservation.release();

    expect(queue.reserve("replacement")).not.toBeNull();
  });

  it("cancels a waiting job without executing it and updates positions", async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
    const active = queue.reserve("active")!;
    const waiting = queue.reserve("waiting")!;
    const last = queue.reserve("last")!;
    const gate = deferred<void>();
    let waitingRan = false;
    const lastPositions: number[] = [];

    const activePromise = active.submit(() => gate.promise, () => undefined);
    const waitingPromise = waiting.submit(async () => {
      waitingRan = true;
    }, () => undefined);
    const lastPromise = last.submit(async () => undefined, position => {
      lastPositions.push(position);
    });

    waiting.release();
    await expect(waitingPromise).rejects.toMatchObject({
      publicCode: "CLIENT_ABORTED"
    });
    expect(waitingRan).toBe(false);
    expect(lastPositions.at(-1)).toBe(1);
    gate.resolve();
    await Promise.all([activePromise, lastPromise]);
  });

  it("aborts the active job signal", async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 1 });
    const reservation = queue.reserve("active")!;
    const observed = deferred<void>();
    const promise = reservation.submit(
      signal =>
        new Promise<void>(resolve => {
          if (signal.aborted) {
            observed.resolve();
            resolve();
            return;
          }
          signal.addEventListener("abort", () => {
            observed.resolve();
            resolve();
          });
        }),
      () => undefined
    );

    reservation.release();
    await observed.promise;
    await promise;
    expect(reservation.signal.aborted).toBe(true);
  });

  it("rejects duplicate job ids and stops accepting on shutdown", async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
    queue.reserve("same");
    expect(() => queue.reserve("same")).toThrow("Duplicate queue job id");

    await queue.shutdown();

    expect(queue.reserve("new")).toBeNull();
    expect(queue.stats()).toEqual({ active: 0, queued: 0, reserved: 0 });
  });
});
