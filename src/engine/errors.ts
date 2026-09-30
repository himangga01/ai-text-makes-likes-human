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

// The internal message is logged; it names only the provider and the signal,
// never the CLI's own text, which can echo the model id or request content.
export function modelUnavailable(provider: "Codex" | "Claude", signal: string): EngineError {
  return new EngineError("MODEL_UNAVAILABLE", false, `${provider} rejected the selected model (${signal})`);
}

// A CLI process failure (login, usage limit, network, crash) fails the job; it
// is not a malformed reply. The reason holds only exit codes and CLI status fields.
export function engineFailed(provider: "Codex" | "Claude", reason: string): EngineError {
  return new EngineError("ENGINE_FAILED", true, `${provider} CLI failed (${reason})`);
}
