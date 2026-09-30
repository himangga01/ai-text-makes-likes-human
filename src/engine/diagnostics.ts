import type { RewriteStrength } from './rewrite-policy.js';
export type RouteHint = "light" | "standard" | "heavy";
export type ProcessingMode = "single" | "chunked";
export type GateCode =
  | "GATE_OK"
  | "GATE_WARN"
  | "GATE_ABORT"
  | "GATE_ERROR";

export interface ChunkTiming {
  codexMs: number;
  restoreMs: number;
  gateMs: number;
}

export interface TransformDiagnostics {
  requestedStrength?: RewriteStrength;
  conservativeRetries?: number;
  candidateReviewRetries?: number;
  skippedSentences?: number;
  fidelityGuardFailures?: number;
  rolledBackChunks?: number;
  unusableModelOutputs?: number;
  protectedSentences?: number;
  restoredProtectedSentences?: number;
  fullSourceRollbacks?: number;
  model: string;
  reasoningEffort: string;
  processingMode: ProcessingMode;
  routeHint: RouteHint | null;
  sourceChars: number;
  bodyChunks: number;
  codexCalls: number;
  retries: number;
  restoredSentences: number;
  removedCommas: number;
  gateCodes: GateCode[];
  maxObservedCodexConcurrency: number;
  prepareMs: number;
  codexMs: number;
  restoreMs: number;
  gateMs: number;
  assembleMs: number;
  totalMs: number;
}
