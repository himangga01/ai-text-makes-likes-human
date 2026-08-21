import { once } from "node:events";
import type { Writable } from "node:stream";
import type { TransformEvent } from "../contracts.js";

export class NdjsonWriter {
  private ended = false;

  constructor(private readonly sink: Writable) {}

  write(event: TransformEvent): boolean {
    if (this.ended || this.sink.destroyed) return false;
    return this.sink.write(`${JSON.stringify(event)}\n`, "utf8");
  }

  async writeAsync(event: TransformEvent): Promise<void> {
    if (this.write(event)) return;
    if (this.ended || this.sink.destroyed) return;
    await once(this.sink, "drain");
  }

  end(): void {
    if (this.ended) return;
    this.ended = true;
    if (!this.sink.destroyed) this.sink.end();
  }
}
