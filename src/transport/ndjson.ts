import type { Writable } from "node:stream";
import type { TransformEvent } from "../contracts.js";

export class NdjsonWriter {
  private ended = false;
  private closed = false;

  constructor(private readonly sink: Writable) {
    sink.once("close", () => {
      this.closed = true;
    });
    sink.once("error", () => {
      this.closed = true;
    });
  }

  get isClosed(): boolean {
    return this.closed || this.sink.destroyed;
  }

  write(event: TransformEvent): boolean {
    if (this.ended || this.isClosed) return false;
    return this.sink.write(`${JSON.stringify(event)}\n`, "utf8");
  }

  async writeAsync(event: TransformEvent): Promise<void> {
    if (this.write(event)) return;
    if (this.ended || this.isClosed) return;
    await new Promise<void>(resolve => {
      const finish = (): void => {
        this.sink.off("drain", finish);
        this.sink.off("close", finish);
        this.sink.off("error", finish);
        resolve();
      };
      this.sink.once("drain", finish);
      this.sink.once("close", finish);
      this.sink.once("error", finish);
    });
  }

  end(): void {
    if (this.ended) return;
    this.ended = true;
    if (!this.isClosed) this.sink.end();
  }
}
