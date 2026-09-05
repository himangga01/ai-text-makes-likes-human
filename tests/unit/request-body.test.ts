import { readFile } from "node:fs/promises";
import { Readable } from "node:stream";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { streamRequestBody } from "../../src/transport/request-body.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

describe("streamRequestBody", () => {
  it("preserves Korean UTF-8 split across byte chunks", async () => {
    const root = await makeTestRoot();
    const destination = path.join(root, "input.txt");
    const encoded = new TextEncoder().encode("한글 입력\n둘째 줄");
    const chunks = [encoded.slice(0, 1), encoded.slice(1, 4), encoded.slice(4)];
    try {
      const result = await streamRequestBody(
        Readable.from(chunks),
        destination,
        {
          minFreeBytes: 1024,
          signal: new AbortController().signal,
          getFreeBytes: async () => 1024 ** 3
        }
      );

      expect(await readFile(destination, "utf8")).toBe("한글 입력\n둘째 줄");
      expect(result.bytes).toBe(encoded.byteLength);
      expect(result.chars).toBe(Array.from("한글 입력\n둘째 줄").length);
    } finally {
      await removeTestRoot(root);
    }
  });

  it("normalises CRLF and bare CR to LF even when split across chunks", async () => {
    const root = await makeTestRoot();
    const destination = path.join(root, "input.txt");
    const chunks = [
      Buffer.from("첫 줄\r", "utf8"),
      Buffer.from("\n둘째 줄\r\n\r", "utf8"),
      Buffer.from("셋째 줄\r", "utf8")
    ];
    try {
      const result = await streamRequestBody(
        Readable.from(chunks),
        destination,
        {
          minFreeBytes: 1024,
          signal: new AbortController().signal,
          getFreeBytes: async () => 1024 ** 3
        }
      );

      const expected = "첫 줄\n둘째 줄\n\n셋째 줄\n";
      expect(await readFile(destination, "utf8")).toBe(expected);
      expect(result.bytes).toBe(Buffer.byteLength(expected, "utf8"));
      expect(result.chars).toBe(Array.from(expected).length);
    } finally {
      await removeTestRoot(root);
    }
  });

  it("rejects whitespace-only input and removes the partial file", async () => {
    const root = await makeTestRoot();
    const destination = path.join(root, "input.txt");
    try {
      await expect(
        streamRequestBody(Readable.from([" \n\t"]), destination, {
          minFreeBytes: 1,
          signal: new AbortController().signal,
          getFreeBytes: async () => 1024
        })
      ).rejects.toMatchObject({ publicCode: "EMPTY_INPUT" });
      await expect(readFile(destination)).rejects.toThrow();
    } finally {
      await removeTestRoot(root);
    }
  });

  it("stops before writing when free space is below the safety floor", async () => {
    const root = await makeTestRoot();
    const destination = path.join(root, "input.txt");
    try {
      await expect(
        streamRequestBody(Readable.from(["내용"]), destination, {
          minFreeBytes: 1024,
          signal: new AbortController().signal,
          getFreeBytes: async () => 100
        })
      ).rejects.toMatchObject({ publicCode: "INSUFFICIENT_DISK" });
      await expect(readFile(destination)).rejects.toThrow();
    } finally {
      await removeTestRoot(root);
    }
  });

  it("stops an already-aborted request without leaving a file", async () => {
    const root = await makeTestRoot();
    const destination = path.join(root, "input.txt");
    const controller = new AbortController();
    controller.abort();
    try {
      await expect(
        streamRequestBody(Readable.from(["내용"]), destination, {
          minFreeBytes: 1,
          signal: controller.signal,
          getFreeBytes: async () => 1024
        })
      ).rejects.toMatchObject({ publicCode: "CLIENT_ABORTED" });
      await expect(readFile(destination)).rejects.toThrow();
    } finally {
      await removeTestRoot(root);
    }
  });

  it("rejects invalid UTF-8 rather than corrupting text", async () => {
    const root = await makeTestRoot();
    const destination = path.join(root, "input.txt");
    try {
      await expect(
        streamRequestBody(
          Readable.from([Uint8Array.of(0xc3, 0x28)]),
          destination,
          {
            minFreeBytes: 1,
            signal: new AbortController().signal,
            getFreeBytes: async () => 1024
          }
        )
      ).rejects.toMatchObject({ publicCode: "INTERNAL_ERROR" });
      await expect(readFile(destination)).rejects.toThrow();
    } finally {
      await removeTestRoot(root);
    }
  });
});
