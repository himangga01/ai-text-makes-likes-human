import { EngineError } from "./errors.js";

interface Waiter {
  grant(): void;
}

function cancelled(): EngineError {
  return new EngineError(
    "CLIENT_ABORTED",
    true,
    "Codex permit wait cancelled"
  );
}

export class CodexSemaphore {
  readonly capacity: number;
  private active = 0;
  private observed = 0;
  private readonly waiters: Waiter[] = [];

  constructor(capacity: number) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new Error("Codex semaphore capacity must be a positive integer");
    }
    this.capacity = capacity;
  }

  get maxObserved(): number {
    return this.observed;
  }

  async run<T>(signal: AbortSignal, task: () => Promise<T>): Promise<T> {
    await this.acquire(signal);
    try {
      return await task();
    } finally {
      this.release();
    }
  }

  private async acquire(signal: AbortSignal): Promise<void> {
    if (signal.aborted) throw cancelled();
    if (this.active < this.capacity) {
      this.active += 1;
      this.observed = Math.max(this.observed, this.active);
      return;
    }

    await new Promise<void>((resolve, reject) => {
      const waiter: Waiter = {
        grant: () => {
          signal.removeEventListener("abort", onAbort);
          this.active += 1;
          this.observed = Math.max(this.observed, this.active);
          resolve();
        }
      };
      const onAbort = (): void => {
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) this.waiters.splice(index, 1);
        reject(cancelled());
      };
      signal.addEventListener("abort", onAbort, { once: true });
      this.waiters.push(waiter);
    });
  }

  private release(): void {
    this.active -= 1;
    this.waiters.shift()?.grant();
  }
}
