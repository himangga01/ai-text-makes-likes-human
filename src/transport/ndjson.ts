import type { Writable } from "node:stream";
import type { TransformEvent } from "../contracts.js";

export const HEARTBEAT_MS = 20_000;

export class NdjsonWriter {
  private ended = false;
  private closed = false;
  private heartbeat: NodeJS.Timeout | undefined;
  private lastWriteAt = Date.now();

  constructor(private readonly sink: Writable) {
    sink.once("close", () => {
      this.closed = true;
      this.stopKeepAlive();
    });
    sink.once("error", () => {
      this.closed = true;
      this.stopKeepAlive();
    });
  }

  get isClosed(): boolean {
    return this.closed || this.sink.destroyed;
  }

  write(event: TransformEvent): boolean {
    if (this.ended || this.isClosed) return false;
    this.lastWriteAt = Date.now();
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

  /** Writes a heartbeat after every `intervalMs` without another event. A proxy in front of the portal
   * (Cloudflare Tunnel closes a response silent for 100 s) must not cut a long model call; clients ignore it. */
  keepAlive(intervalMs: number): void {
    if (this.heartbeat || intervalMs <= 0) return;
    this.heartbeat = setInterval(() => {
      if (this.ended || this.isClosed) { this.stopKeepAlive(); return; }
      if (Date.now() - this.lastWriteAt >= intervalMs) this.write({ type: "heartbeat" });
    }, Math.max(1, Math.floor(intervalMs / 2)));
    this.heartbeat.unref();
  }

  private stopKeepAlive(): void {
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = undefined;
  }

  end(): void {
    this.stopKeepAlive();
    if (this.ended) return;
    this.ended = true;
    if (!this.isClosed) this.sink.end();
  }
}
