export type TransformPhase =
  | "sanitize"
  | "chunk"
  | "transform"
  | "verify"
  | "assemble";

export type PublicErrorCode =
  | "EMPTY_INPUT"
  | "QUEUE_FULL"
  | "ENGINE_UNAVAILABLE"
  | "ENGINE_TIMEOUT"
  | "ENGINE_OUTPUT_INVALID"
  | "VALIDATION_FAILED"
  | "INSUFFICIENT_DISK"
  | "CLIENT_ABORTED"
  | "INTERNAL_ERROR";

export type TransformEvent =
  | { type: "accepted"; jobId: string; position: number }
  | { type: "queued"; position: number }
  | {
      type: "progress";
      phase: TransformPhase;
      current: number;
      total: number;
      message: string;
    }
  | { type: "result-start" }
  | { type: "result-delta"; text: string }
  | { type: "warning"; code: string; message: string }
  | {
      type: "done";
      sourceChars: number;
      outputChars: number;
      chunks: number;
      elapsedMs: number;
    }
  | {
      type: "error";
      code: PublicErrorCode;
      message: string;
      retryable: boolean;
    };

export type EventSink = (event: TransformEvent) => void;
