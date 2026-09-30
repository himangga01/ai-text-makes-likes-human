import { expect, it } from "vitest";
import { createShutdownSignalHandler } from "../../src/runtime/shutdown-signal.js";

function harness() {
  let now = 0;
  const calls: string[] = [];
  const handler = createShutdownSignalHandler({
    graceful: () => calls.push("graceful"),
    force: () => calls.push("force"),
    now: () => now
  });
  return { calls, handler, advance: (ms: number) => { now += ms; } };
}

it("treats a signal repeated within a second as the same Ctrl-C", () => {
  // npm and `tsx watch` forward the terminal's SIGINT, so node receives it twice at once.
  const { calls, handler, advance } = harness();
  handler();
  advance(3);
  handler();
  expect(calls).toEqual(["graceful"]);
});

it("forces the exit on a deliberate second signal", () => {
  const { calls, handler, advance } = harness();
  handler();
  advance(1_000);
  handler();
  expect(calls).toEqual(["graceful", "force"]);
});
