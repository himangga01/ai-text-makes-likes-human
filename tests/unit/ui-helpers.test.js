import { describe, expect, it, vi } from "vitest";
import { decodeTextBytes, getTextDownloadName } from "../../public/text-file.js";
import { displayMessage, effortLabel, resolveModelSelection } from "../../public/connection-settings.js";
import { createDiffCopyHandlers } from "../../public/result-diff.js";

const options = [
  { id: "gpt-5.6-sol", label: "GPT-5.6 Sol", efforts: ["low", "medium", "high", "xhigh", "max", "ultra"] },
  { id: "gpt-6-luna", label: "GPT-6 Luna", efforts: ["low", "medium", "high", "xhigh", "max"] }
];
const fallback = { model: "gpt-5.6-sol", effort: "medium" };

describe("model selection restore", () => {
  it("replaces a removed model with the engine default model and default effort", () => {
    expect(resolveModelSelection(options, { model: "gpt-5.5", effort: "xhigh" }, fallback))
      .toEqual({ model: "gpt-5.6-sol", effort: "medium", replaced: "gpt-5.5" });
  });
  it("keeps a valid saved pair and repairs an invalid effort with the engine default", () => {
    expect(resolveModelSelection(options, { model: "gpt-6-luna", effort: "max" }, fallback)).toEqual({ model: "gpt-6-luna", effort: "max", replaced: undefined });
    expect(resolveModelSelection(options, { model: "gpt-6-luna", effort: "ultra" }, fallback)).toEqual({ model: "gpt-6-luna", effort: "medium", replaced: undefined });
    const claude = [{ id: "claude-opus-5-5", label: "Claude Opus 5.5", efforts: ["low", "medium", "high", "xhigh", "max"] }];
    expect(resolveModelSelection(claude, { model: "claude-opus-5-5" }, { model: "claude-fable-5-1", effort: "high" }))
      .toEqual({ model: "claude-opus-5-5", effort: "high", replaced: undefined });
  });
  it("uses the first option when the default model itself is missing", () => {
    expect(resolveModelSelection(options.slice(1), undefined, fallback)).toEqual({ model: "gpt-6-luna", effort: "medium", replaced: undefined });
  });
  it("marks only the engine default effort as default", () => {
    expect(effortLabel("high", "high")).toBe("High · 깊게 · 기본");
    expect(effortLabel("medium", "high")).not.toContain("기본");
    expect(effortLabel("medium", "medium")).toContain("· 기본");
  });
});

describe("text file edge cases", () => {
  it("reports invalid BOM-marked bytes as a Korean decode error", () => {
    for (const bytes of [Uint8Array.of(0xff, 0xfe, 0x00), Uint8Array.of(0xfe, 0xff, 0x00), Uint8Array.of(0xef, 0xbb, 0xbf, 0xff)]) {
      expect(() => decodeTextBytes(bytes)).toThrow(expect.objectContaining({ name: "TextFileError", code: "TEXT_FILE_DECODE_FAILED" }));
    }
  });
  it("rejects BOM-less UTF-16 instead of passing NUL-filled UTF-8", () => {
    expect(() => decodeTextBytes(Uint8Array.of(0x61, 0x00, 0x62, 0x00))).toThrow(expect.objectContaining({ code: "TEXT_FILE_UNSUPPORTED_ENCODING" }));
  });
  it("never offers the source TXT name as the result name", () => {
    expect(getTextDownloadName("memo.txt")).toBe("memo-humanized.txt");
    expect(getTextDownloadName("memo.TXT")).toBe("memo-humanized.txt");
    expect(getTextDownloadName(undefined)).toBe("humanized.txt");
  });
});

describe("diff copy interception", () => {
  function handlers({ hiddenAncestor = false, empty = false } = {}) {
    const changes = { closest: selector => (selector === "[hidden]" && hiddenAncestor ? {} : null), hasChildNodes: () => !empty, contains: () => false };
    const range = { intersectsNode: () => true, startContainer: {}, endContainer: {} };
    const selection = { rangeCount: 1, isCollapsed: false, getRangeAt: () => range, toString: () => "x" };
    return createDiffCopyHandlers({ root: {}, changes, onStatus: vi.fn(), getSelection: () => selection });
  }
  it("leaves native copy alone when the comparison is hidden or empty", () => {
    for (const state of [{ hiddenAncestor: true }, { empty: true }]) {
      const event = { preventDefault: vi.fn() };
      expect(handlers(state).handleCopy(event)).toBe("unhandled");
      expect(event.preventDefault).not.toHaveBeenCalled();
    }
    const event = { preventDefault: vi.fn() };
    expect(handlers().handleCopy(event)).toBe("outside");
  });
});

describe("text diff without Intl.Segmenter", () => {
  it("loads and diffs on browsers that lack Intl.Segmenter", async () => {
    const original = Intl.Segmenter;
    vi.resetModules();
    try {
      Intl.Segmenter = undefined;
      const { diffText } = await import("../../public/text-diff.js?no-segmenter");
      const result = diffText("가나 다라\n", "가나 마라\n");
      expect(result.segments.filter(s => s.type !== "delete").map(s => s.text).join("")).toBe("가나 마라\n");
    } finally { Intl.Segmenter = original; }
  });
});

describe("displayMessage", () => {
  it("strips the Electron IPC prefix and keeps other messages", () => {
    expect(displayMessage("Error invoking remote method 'humanize:save-text': Error: 원본과 다른 새 파일 이름을 지정해 주세요.")).toBe("원본과 다른 새 파일 이름을 지정해 주세요.");
    expect(displayMessage("Error invoking remote method 'humanize:transform': TypeError: 이미 변환 중입니다.")).toBe("이미 변환 중입니다.");
    expect(displayMessage("변환을 취소했습니다.")).toBe("변환을 취소했습니다.");
    expect(displayMessage(undefined)).toBe("");
  });
});
