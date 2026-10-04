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
  /** Fixed gate failure codes per job (no text), e.g. {"polarity_changed": 2}. */
  hardFailureCounts?: Record<string, number>;
  /** Codes Super Sejong would have blocked on in enforce mode (shadow mode only). */
  shadowFailureCounts?: Record<string, number>;
  /** Super Sejong style findings in the source chunks and in the delivered chunks. */
  styleFindingsBefore?: number;
  styleFindingsAfter?: number;
  /** Particle allomorph mismatches introduced by the rewrite and repaired deterministically. */
  repairedParticles?: number;
  protectedSentences?: number;
  restoredProtectedSentences?: number;
  fullSourceRollbacks?: number;
  /* Super Sejong v2 only (DESIGN 5.2): codes and counts, never text. The legacy engine leaves them unset. */
  /** Engine that produced the delivered text. */
  engine?: "legacy" | "v2";
  /** Body chunks whose plan needed no writer call (SEJONG_NO_EDIT_NEEDED). */
  chunksWithoutModelCall?: number;
  /** Plan requests by tier; REVIEW counts the writer's open-review nominations. */
  planRequests?: Record<"FIX" | "SUGGEST" | "REVIEW", number>;
  /** Final request outcomes: FIXED, UNTOUCHED, STILL_PRESENT, LOST, DECLINED. */
  requestStatus?: Record<string, number>;
  /** Sentences put back to their base text, by verification family (seam reverts count as flow). */
  revertedSentences?: Record<string, number>;
  collateralReverts?: number;
  voiceGrafts?: number;
  cmcRestored?: number;
  normFixes?: number;
  /** Sentences sent to the targeted retry. */
  sentenceRetries?: number;
  /** Legacy shadow mode only (SUPER_SEJONG_V2_SHADOW=1): fixed keys and integer counts of what Super Sejong v2 would have done on the side. Never text. */
  v2ShadowCounts?: Record<string, number>;
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
