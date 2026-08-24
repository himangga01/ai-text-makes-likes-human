import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";

export type RouteHint = "light" | "standard" | "heavy";
export type ProcessingMode = "single" | "chunked";
export type GateCode =
  | "GATE_OK"
  | "GATE_WARN"
  | "GATE_ABORT"
  | "GATE_ERROR";

export interface ChunkTiming {
  codexMs: number;
  gateMs: number;
}

export interface TransformDiagnostics {
  model: typeof HUMANIZE_MODEL;
  reasoningEffort: typeof HUMANIZE_REASONING_EFFORT;
  processingMode: ProcessingMode;
  routeHint: RouteHint | null;
  sourceChars: number;
  bodyChunks: number;
  codexCalls: number;
  retries: number;
  gateCodes: GateCode[];
  maxObservedCodexConcurrency: number;
  prepareMs: number;
  codexMs: number;
  gateMs: number;
  assembleMs: number;
  totalMs: number;
}
