import { readdir, writeFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { EngineError } from "../../src/engine/errors.js";
import type {
  PythonAdapter
} from "../../src/engine/humanize-engine.js";
import type { GateCode } from "../../src/engine/diagnostics.js";
import type { GateResult } from "../../src/engine/python-engine.js";
import {
  executeLiveEngineFixture,
  observePythonGates
} from "../helpers/live-engine.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

describe("live engine failure metadata", () => {
  it("sanitizes a transform failure after verifying workspace cleanup", async () => {
    const runtimeRoot = await makeTestRoot("live-failure-");
    const times = [100, 145];
    try {
      let failure: unknown;
      try {
        await executeLiveEngineFixture("deterministic input", {
          runtimeRoot,
          engine: {
            async transform(request) {
              await writeFile(
                request.workspace.path("partial.txt"),
                "temporary output",
                "utf8"
              );
              throw new EngineError(
                "VALIDATION_FAILED",
                false,
                "private source and path must not escape"
              );
            }
          },
          observedGateCodes: () => [
            "GATE_OK",
            "NOT_ALLOWLISTED" as GateCode,
            "GATE_ABORT"
          ],
          now: () => times.shift()!
        });
      } catch (error) {
        failure = error;
      }

      expect(failure).toEqual({
        publicCode: "VALIDATION_FAILED",
        gateCodes: ["GATE_OK", "GATE_ABORT"],
        elapsedMs: 45,
        cleanup: true
      });
      expect(Object.keys(failure as object).sort()).toEqual([
        "cleanup",
        "elapsedMs",
        "gateCodes",
        "publicCode"
      ]);
      expect(await readdir(runtimeRoot)).toEqual([]);
    } finally {
      await removeTestRoot(runtimeRoot);
    }
  });

  it("collects allowlisted gate codes through the final full-document gate", async () => {
    const results: GateResult[] = [
      { status: "ok", exitCode: 0, gateCodes: ["GATE_OK"] },
      {
        status: "abort",
        exitCode: 2,
        gateCodes: ["UNSAFE" as GateCode, "GATE_ABORT"]
      }
    ];
    const python: PythonAdapter = {
      async prepare() {
        throw new Error("unused");
      },
      async restore() {
        throw new Error("unused");
      },
      async reassemble() {
        throw new Error("unused");
      },
      async verify() {
        return results.shift()!;
      }
    };

    const observed = observePythonGates(python);
    const signal = new AbortController().signal;
    await observed.python.verify("before", "after", signal);
    await observed.python.verify("before", "after", signal);

    expect(observed.gateCodes()).toEqual(["GATE_OK", "GATE_ABORT"]);
  });
});
