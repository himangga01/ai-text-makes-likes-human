import { describe, expect, it } from "vitest";
import { progressForEvent } from "../../public/progress.js";

describe("progressForEvent", () => {
  it("maps fixed and chunk-based progress phases to their hand-derived percentages", () => {
    expect(progressForEvent({ type: "accepted" })).toBe(2);
    expect(progressForEvent({ type: "progress", phase: "sanitize" })).toBe(5);
    expect(progressForEvent({ type: "progress", phase: "chunk" })).toBe(15);
    expect(progressForEvent({ type: "progress", phase: "transform", current: 2, total: 4 })).toBe(28.75);
    expect(progressForEvent({ type: "progress", phase: "verify", current: 2, total: 4 })).toBe(35.625);
    expect(progressForEvent({ type: "progress", phase: "assemble" })).toBe(90);
  });

  it("advances monotonically through two transformed and verified chunks", () => {
    const progress = [
      progressForEvent({ type: "progress", phase: "transform", current: 1, total: 2 }),
      progressForEvent({ type: "progress", phase: "verify", current: 1, total: 2 }),
      progressForEvent({ type: "progress", phase: "transform", current: 2, total: 2 }),
      progressForEvent({ type: "progress", phase: "verify", current: 2, total: 2 })
    ];

    expect(progress).toEqual([15, 28.75, 42.5, 56.25]);
    expect(progress.every((value, index) => index === 0 || value > progress[index - 1])).toBe(true);
  });

  it("prefers aggregate work units over out-of-order chunk phases", () => {
    expect(progressForEvent({
      type: "progress",
      phase: "transform",
      current: 4,
      total: 4,
      completedUnits: 1,
      totalUnits: 4
    })).toBe(33.75);
    expect(progressForEvent({
      type: "progress",
      phase: "verify",
      current: 1,
      total: 4,
      completedUnits: 4,
      totalUnits: 4
    })).toBe(90);
  });

  it("returns null for queued work so the progress control is indeterminate", () => {
    expect(progressForEvent({ type: "queued", position: 3 })).toBeNull();
  });

  it("maps result streaming and completion events to terminal progress", () => {
    expect(progressForEvent({ type: "result-start" })).toBe(95);
    expect(progressForEvent({ type: "result-delta", text: "partial result" })).toBe(95);
    expect(progressForEvent({ type: "done" })).toBe(100);
  });

  it("never returns NaN for malformed progress values and preserves unrelated events", () => {
    const malformed = [
      { type: "progress", phase: "transform", current: Number.NaN, total: 0 },
      { type: "progress", phase: "verify", current: Infinity, total: "bad" },
      { type: "progress", phase: "transform", current: -10, total: -2 }
    ];

    for (const event of malformed) {
      const value = progressForEvent(event);
      expect(typeof value).toBe("number");
      expect(Number.isNaN(value)).toBe(false);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(100);
    }
    expect(progressForEvent({ type: "warning" })).toBeUndefined();
    expect(progressForEvent({ type: "error" })).toBeUndefined();
    expect(progressForEvent({ type: "new-event" })).toBeUndefined();
  });

  it("falls back to phase progress for malformed aggregate sequences", () => {
    const malformed = [
      { completedUnits: 0, totalUnits: 0 },
      { completedUnits: 1, totalUnits: 0 },
      { completedUnits: 3, totalUnits: 2 },
      { completedUnits: 2, totalUnits: -1 },
      { completedUnits: 4, totalUnits: Number.NaN }
    ];

    expect(malformed.map(fields => progressForEvent({
      type: "progress",
      phase: "transform",
      current: 2,
      total: 4,
      ...fields
    }))).toEqual([28.75, 28.75, 28.75, 28.75, 28.75]);
  });
});
