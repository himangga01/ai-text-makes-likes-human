import { PassThrough, Writable } from "node:stream";
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

  it("unblocks backpressure when the client closes before drain", async () => {
    class ClosingWritable extends Writable {
      constructor() {
        super({ highWaterMark: 1 });
      }
      override _write(
        _chunk: Buffer,
        _encoding: BufferEncoding,
        _callback: (error?: Error | null) => void
      ): void {
        setTimeout(() => this.emit("close"), 10);
      }
    }
    const sink = new ClosingWritable();
    const writer = new NdjsonWriter(sink);

    const outcome = await Promise.race([
      writer
        .writeAsync({ type: "result-delta", text: "긴 결과".repeat(20) })
        .then(() => "resolved"),
      new Promise<string>(resolve =>
        setTimeout(() => resolve("timed-out"), 200)
      )
    ]);

    expect(outcome).toBe("resolved");
    expect(writer.isClosed).toBe(true);
  });
});
