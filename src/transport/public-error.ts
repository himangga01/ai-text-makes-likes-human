import type { PublicErrorCode, TransformEvent } from "../contracts.js";
import { EngineError } from "../engine/errors.js";

export const PUBLIC_MESSAGES: Record<PublicErrorCode, string> = {
  EMPTY_INPUT: "원본 문구를 입력해 주세요.",
  QUEUE_FULL: "현재 3건이 처리 중입니다. 잠시 후 다시 시도해 주세요.",
  ENGINE_UNAVAILABLE: "서버의 변환 엔진을 사용할 수 없습니다.",
  ENGINE_TIMEOUT: "한 구간의 처리 시간이 초과되었습니다.",
  ENGINE_OUTPUT_INVALID: "변환 결과 형식을 확인하지 못했습니다.",
  ENGINE_FAILED: "CLI 실행에 실패했습니다. 로그인 상태와 사용 한도를 확인한 뒤 다시 시도해 주세요.",
  VALIDATION_FAILED: "내용 보존 검증을 통과하지 못했습니다.",
  INSUFFICIENT_DISK: "서버 저장 공간이 부족합니다.",
  CLIENT_ABORTED: "변환을 취소했습니다.",
  MODEL_UNAVAILABLE: "선택한 모델을 사용할 수 없습니다. CLI를 최신 버전으로 업데이트했는지와 계정의 모델 이용 권한을 확인해 주세요.",
  SERVER_SHUTDOWN: "서버가 재시작되어 변환이 중단되었습니다. 잠시 후 다시 시도해 주세요.",
  INTERNAL_ERROR: "처리 중 오류가 발생했습니다. 다시 시도해 주세요."
};

// A job cut off by server shutdown surfaces as a cancellation from the queue or
// the CLI runner. The client did not cancel it, so it must not read as its own.
export function shutdownAware(error: unknown, shuttingDown: boolean, clientAborted: boolean): unknown {
  if (!shuttingDown || clientAborted) return error;
  if (error instanceof EngineError && error.publicCode !== "CLIENT_ABORTED") return error;
  return new EngineError("SERVER_SHUTDOWN", true, "Server shut down during the job", { cause: error });
}

export function publicEvent(error: unknown): Extract<TransformEvent, { type: "error" }> {
  if (error instanceof EngineError) {
    return {
      type: "error",
      code: error.publicCode,
      message: PUBLIC_MESSAGES[error.publicCode],
      retryable: error.retryable
    };
  }
  return {
    type: "error",
    code: "INTERNAL_ERROR",
    message: PUBLIC_MESSAGES.INTERNAL_ERROR,
    retryable: false
  };
}
