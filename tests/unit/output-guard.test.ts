import { describe, expect, it } from "vitest";
import { assertNoForeignEmail } from "../../src/engine/output-guard.js";

describe("assertNoForeignEmail", () => {
  it("accepts addresses that the prompt already contained, whatever their case", () => {
    expect(() => assertNoForeignEmail("문의: Help@Example.com 으로 보내 주세요.",
      JSON.stringify({ rewrittenText: "문의는 help@example.com으로 보내 주세요." }), "Codex")).not.toThrow();
    expect(() => assertNoForeignEmail("주소 없음", JSON.stringify({ rewrittenText: "주소가 없다." }), "Codex")).not.toThrow();
  });

  it("refuses a reply that introduces an address", () => {
    expect(() => assertNoForeignEmail("원문", JSON.stringify({ rewrittenText: "연락처는 owner@example.org 이다." }), "Claude"))
      .toThrow(expect.objectContaining({ publicCode: "ENGINE_OUTPUT_INVALID" }));
  });

  it("decodes JSON escapes and full-width forms before looking", () => {
    expect(() => assertNoForeignEmail("원문", '{"rewrittenText":"owner\\u0040example.org"}', "Claude")).toThrow();
    expect(() => assertNoForeignEmail("원문", JSON.stringify({ t: "ｏｗｎｅｒ＠ｅｘａｍｐｌｅ．ｏｒｇ" }), "Claude")).toThrow();
  });

  it("checks plain-text replies too", () => {
    expect(() => assertNoForeignEmail("원문", "a@b.co", "Codex")).toThrow();
  });
});
