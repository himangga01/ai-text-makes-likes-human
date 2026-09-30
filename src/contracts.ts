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
  | "ENGINE_FAILED"
  | "VALIDATION_FAILED"
  | "INSUFFICIENT_DISK"
  | "CLIENT_ABORTED"
  | "MODEL_UNAVAILABLE"
  | "SERVER_SHUTDOWN"
  | "INTERNAL_ERROR";

export type TransformProgressEvent = {
  type: "progress";
  phase: TransformPhase;
  current: number;
  total: number;
  completedUnits?: number;
  totalUnits?: number;
  message: string;
};

export type TransformEvent =
  | { type: "document-result"; artifactId: string; name: string; format: "docx"|"pptx"; bytes: number; sha256: string; preview: string }
  | { type: "accepted"; jobId: string; position: number }
  | { type: "queued"; position: number }
  | TransformProgressEvent
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
