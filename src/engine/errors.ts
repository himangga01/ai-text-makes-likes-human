import type { PublicErrorCode } from "../contracts.js";

export class EngineError extends Error {
  constructor(
    public readonly publicCode: PublicErrorCode,
    public readonly retryable: boolean,
    message: string,
    options?: ErrorOptions
  ) {
    super(message, options);
    this.name = "EngineError";
  }
}
