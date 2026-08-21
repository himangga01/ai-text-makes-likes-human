import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { NdjsonWriter } from "../../src/transport/ndjson.js";

describe("NdjsonWriter", () => {
  it("writes one escaped JSON event per line", async () => {
    const sink = new PassThrough();
    sink.setEncoding("utf8");
    let text = "";
    sink.on("data", chunk => {
      text += String(chunk);
    });
    const ended = new Promise<void>(resolve => sink.on("end", resolve));
    const writer = new NdjsonWriter(sink);

    writer.write({ type: "queued", position: 2 });
    writer.write({ type: "result-delta", text: "한글\n두 줄" });
    writer.end();
    await ended;

    expect(text).toBe(
      '{"type":"queued","position":2}\n' +
        '{"type":"result-delta","text":"한글\\n두 줄"}\n'
    );
  });
});
