import { EngineError } from "../engine/errors.js";

export interface QueueStats {
  active: number;
  queued: number;
  reserved: number;
}

export interface TransformQueueOptions {
  maxActive: number;
  maxAccepted: number;
}

type JobState = "reserved" | "queued" | "active" | "released" | "finished";

interface JobRecord {
  id: string;
  state: JobState;
  controller: AbortController;
  execute?: (signal: AbortSignal) => Promise<void>;
  onPosition?: (position: number) => void;
  resolve?: () => void;
  reject?: (reason: unknown) => void;
  promise?: Promise<void>;
}

function cancellation(): EngineError {
  return new EngineError("CLIENT_ABORTED", true, "Queue job was cancelled");
}

export class QueueReservation {
  constructor(
    private readonly queue: TransformQueue,
    private readonly record: JobRecord
  ) {}

  get signal(): AbortSignal {
    return this.record.controller.signal;
  }

  submit(
    execute: (signal: AbortSignal) => Promise<void>,
    onPosition: (position: number) => void
  ): Promise<void> {
    return this.queue.submit(this.record, execute, onPosition);
  }

  release(): void {
    this.queue.release(this.record);
  }
}

export class TransformQueue {
  private readonly maxActive: number;
  private readonly maxAccepted: number;
  private accepting = true;
  private readonly reserved = new Map<string, JobRecord>();
  private readonly waiting: JobRecord[] = [];
  private readonly active = new Map<string, JobRecord>();

  constructor(options: TransformQueueOptions) {
    if (
      !Number.isInteger(options.maxActive) ||
      !Number.isInteger(options.maxAccepted) ||
      options.maxActive < 1 ||
      options.maxAccepted < options.maxActive
    ) {
      throw new Error("Invalid queue capacity");
    }
    this.maxActive = options.maxActive;
    this.maxAccepted = options.maxAccepted;
  }

  get isShuttingDown(): boolean {
    return !this.accepting;
  }

  stats(): QueueStats {
    return {
      active: this.active.size,
      queued: this.waiting.length,
      reserved: this.reserved.size
    };
  }

  reserve(jobId: string): QueueReservation | null {
    if (!this.accepting) return null;
    if (
      this.reserved.has(jobId) ||
      this.active.has(jobId) ||
      this.waiting.some(record => record.id === jobId)
    ) {
      throw new Error("Duplicate queue job id");
    }
    const stats = this.stats();
    if (stats.active + stats.queued + stats.reserved >= this.maxAccepted) {
      return null;
    }

    const record: JobRecord = {
      id: jobId,
      state: "reserved",
      controller: new AbortController()
    };
    this.reserved.set(jobId, record);
    return new QueueReservation(this, record);
  }

  submit(
    record: JobRecord,
    execute: (signal: AbortSignal) => Promise<void>,
    onPosition: (position: number) => void
  ): Promise<void> {
    if (record.state !== "reserved" || !this.reserved.has(record.id)) {
      throw new Error("Queue reservation is no longer available");
    }

    this.reserved.delete(record.id);
    record.state = "queued";
    record.execute = execute;
    record.onPosition = onPosition;
    record.promise = new Promise<void>((resolve, reject) => {
      record.resolve = resolve;
      record.reject = reject;
    });
    this.waiting.push(record);
    this.pump();
    this.updatePositions();
    return record.promise;
  }

  release(record: JobRecord): void {
    if (record.state === "released" || record.state === "finished") return;

    if (record.state === "reserved") {
      this.reserved.delete(record.id);
      record.controller.abort();
      record.state = "released";
      return;
    }

    if (record.state === "queued") {
      const index = this.waiting.indexOf(record);
      if (index >= 0) this.waiting.splice(index, 1);
      record.controller.abort();
      record.state = "released";
      record.reject?.(cancellation());
      this.updatePositions();
      this.pump();
      return;
    }

    if (record.state === "active") {
      record.controller.abort();
      record.state = "released";
    }
  }

  private updatePositions(): void {
    for (let index = 0; index < this.waiting.length; index += 1) {
      try {
        this.waiting[index]?.onPosition?.(index + 1);
      } catch {
        // Status reporting must not break queue progress.
      }
    }
  }

  private pump(): void {
    while (this.active.size < this.maxActive && this.waiting.length > 0) {
      const record = this.waiting.shift()!;
      if (record.state !== "queued") continue;
      record.state = "active";
      this.active.set(record.id, record);
      this.updatePositions();

      Promise.resolve()
        .then(() => record.execute!(record.controller.signal))
        .then(
          () => record.resolve?.(),
          error => record.reject?.(error)
        )
        .finally(() => {
          this.active.delete(record.id);
          record.state = "finished";
          this.pump();
        })
        .catch(() => {
          // The externally returned job promise carries the execution error.
        });
    }
  }

  async shutdown(): Promise<void> {
    this.accepting = false;
    for (const record of [...this.reserved.values()]) this.release(record);
    for (const record of [...this.waiting]) this.release(record);
    const activePromises = [...this.active.values()].map(record => record.promise!);
    for (const record of [...this.active.values()]) this.release(record);
    await Promise.allSettled(activePromises);
  }
}
