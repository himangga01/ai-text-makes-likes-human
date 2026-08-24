import { describe, expect, it } from "vitest";
import {
  decodeTextBytes,
  getMarkdownDownloadName,
  readTextFile
} from "../../public/text-file.js";

describe("text file decoding", () => {
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

  it("accepts Markdown files and reports their format", async () => {
    const file = new File(["# 제목\n\n본문"], "memo.MD", {
      type: "text/markdown"
    });

    await expect(readTextFile(file)).resolves.toEqual({
      text: "# 제목\n\n본문",
      encoding: "UTF-8",
      fileName: "memo.MD",
      format: "markdown"
    });
  });

  it("reports TXT files as plain text", async () => {
    const file = new File(["본문"], "memo.txt", { type: "text/plain" });

    await expect(readTextFile(file)).resolves.toMatchObject({
      fileName: "memo.txt",
      format: "text"
    });
  });

  it("derives a stable Markdown result filename", () => {
    expect(getMarkdownDownloadName("notes.v2.MD")).toBe(
      "notes.v2-humanized.md"
    );
    expect(getMarkdownDownloadName(".md")).toBe("humanized.md");
  });

  it("rejects unsupported files before reading them", async () => {
    const file = new File(["내용"], "memo.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });
    await expect(readTextFile(file)).rejects.toMatchObject({
      code: "INVALID_TEXT_FILE"
    });
  });
});
