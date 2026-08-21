import { describe, expect, it } from "vitest";
import {
  decodeTextBytes,
  readTextFile
} from "../../public/text-file.js";

describe("TXT decoding", () => {
  it("removes a UTF-8 BOM", () => {
    const body = new TextEncoder().encode("안녕");
    const bytes = Uint8Array.from([0xef, 0xbb, 0xbf, ...body]);
    expect(decodeTextBytes(bytes)).toEqual({ text: "안녕", encoding: "UTF-8" });
  });

  it("decodes UTF-16 little and big endian BOM files", () => {
    expect(decodeTextBytes(Uint8Array.of(0xff, 0xfe, 0x00, 0xac))).toEqual({
      text: "가",
      encoding: "UTF-16LE"
    });
    expect(decodeTextBytes(Uint8Array.of(0xfe, 0xff, 0xac, 0x00))).toEqual({
      text: "가",
      encoding: "UTF-16BE"
    });
  });

  it("falls back to the browser euc-kr decoder for CP949-family Korean", () => {
    expect(decodeTextBytes(Uint8Array.of(0xb0, 0xa1, 0xb1, 0xdb))).toEqual({
      text: "가글",
      encoding: "CP949/EUC-KR"
    });
  });

  it("rejects a non-txt file before reading it", async () => {
    const file = new File(["내용"], "memo.md", { type: "text/markdown" });
    await expect(readTextFile(file)).rejects.toMatchObject({
      code: "INVALID_TEXT_FILE"
    });
  });
});
