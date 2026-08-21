import { randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import express, { type Express } from "express";
import type { AppConfig } from "./config.js";
import type { TransformEvent } from "./contracts.js";
import { CodexRunner } from "./engine/codex-runner.js";
import { EngineError } from "./engine/errors.js";
import {
  HumanizeEngine,
  type HumanizeRequest,
  type HumanizeResult
} from "./engine/humanize-engine.js";
import { PythonEngine } from "./engine/python-engine.js";
import { JobWorkspace } from "./engine/workspace.js";
import { isAllowedClientAddress } from "./network/private-address.js";
import type { CommandRunner } from "./process/command-runner.js";
import { runPreflight, type PreflightReport } from "./process/preflight.js";
import { TransformQueue } from "./queue/transform-queue.js";
import { NdjsonWriter } from "./transport/ndjson.js";
import { streamRequestBody } from "./transport/request-body.js";

export interface AppLogger {
  info(value: Record<string, unknown>): void;
  error(value: Record<string, unknown>): void;
}

export interface HumanizeService {
  transform(request: HumanizeRequest): Promise<HumanizeResult>;
}

export interface AppDependencies {
  config: AppConfig;
  queue: TransformQueue;
  engine: HumanizeService;
  preflight: PreflightReport;
  logger?: AppLogger;
}

export interface ProductionRuntime {
  engine: HumanizeEngine;
  queue: TransformQueue;
  preflight: PreflightReport;
}

const defaultLogger: AppLogger = {
  info: value => console.log(JSON.stringify(value)),
  error: value => console.error(JSON.stringify(value))
};

const PUBLIC_MESSAGES = {
  EMPTY_INPUT: "원본 문구를 입력해 주세요.",
  QUEUE_FULL: "현재 3건이 처리 중입니다. 잠시 후 다시 시도해 주세요.",
  ENGINE_UNAVAILABLE: "서버의 변환 엔진을 사용할 수 없습니다.",
  ENGINE_TIMEOUT: "한 구간의 처리 시간이 초과되었습니다.",
  ENGINE_OUTPUT_INVALID: "변환 결과 형식을 확인하지 못했습니다.",
  VALIDATION_FAILED: "내용 보존 검증을 통과하지 못했습니다.",
  INSUFFICIENT_DISK: "서버 저장 공간이 부족합니다.",
  CLIENT_ABORTED: "변환을 취소했습니다.",
  INTERNAL_ERROR: "처리 중 오류가 발생했습니다. 다시 시도해 주세요."
} as const;

function publicEvent(error: unknown): TransformEvent {
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

export async function createProductionRuntime(
  config: AppConfig,
  runner: CommandRunner
): Promise<ProductionRuntime> {
  const engineVersion = await readFile(
    path.join(config.vendorRoot, "ENGINE_VERSION"),
    "utf8"
  );
  const preflight = await runPreflight(config, runner, engineVersion);
  const python = new PythonEngine({
    pythonCommand: config.pythonCommand,
    vendorRoot: config.vendorRoot,
    runner
  });
  const codex = new CodexRunner({
    codexCommand: config.codexCommand,
    schemaPath: path.join(config.projectRoot, "src", "engine", "output-schema.json"),
    quickRulesPath: path.join(
      config.vendorRoot,
      "skills",
      "humanize-korean",
      "references",
      "quick-rules.md"
    ),
    timeoutMs: config.chunkTimeoutMs,
    runner
  });
  return {
    engine: new HumanizeEngine({ python, codex }),
    queue: new TransformQueue({
      maxActive: config.maxActiveJobs,
      maxAccepted: config.maxAcceptedJobs
    }),
    preflight
  };
}

async function streamResult(
  writer: NdjsonWriter,
  finalPath: string
): Promise<void> {
  const stream = createReadStream(finalPath, {
    encoding: "utf8",
    highWaterMark: 32 * 1024
  });
  for await (const chunk of stream) {
    await writer.writeAsync({ type: "result-delta", text: String(chunk) });
  }
}

export function createApp(dependencies: AppDependencies): Express {
  const { config, queue, engine, preflight } = dependencies;
  const logger = dependencies.logger ?? defaultLogger;
  const app = express();
  app.disable("x-powered-by");

  app.use((request, response, next) => {
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("Referrer-Policy", "no-referrer");
    response.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    );
    if (!isAllowedClientAddress(request.socket.remoteAddress)) {
      response.status(403).json({
        code: "LAN_ONLY",
        message: "같은 와이파이에서만 접속할 수 있습니다."
      });
      return;
    }
    next();
  });

  app.get("/api/health", (_request, response) => {
    const stats = queue.stats();
    response.setHeader("Cache-Control", "no-store");
    if (!preflight.ready) {
      response.status(503).json({
        status: "degraded",
        errorCode: preflight.errorCode ?? "ENGINE_UNAVAILABLE",
        message:
          preflight.message ?? "서버의 변환 엔진을 사용할 수 없습니다.",
        activeJobs: stats.active,
        queuedJobs: stats.queued
      });
      return;
    }
    response.json({
      status: "ready",
      engine: "codex-cli",
      engineVersion: preflight.codexVersion,
      humanizeVersion: preflight.humanizeVersion,
      activeJobs: stats.active,
      queuedJobs: stats.queued
    });
  });

  app.post("/api/transform", async (request, response) => {
    if (!preflight.ready) {
      response.status(503).json({
        code: "ENGINE_UNAVAILABLE",
        message: PUBLIC_MESSAGES.ENGINE_UNAVAILABLE
      });
      return;
    }
    if (!request.is("text/plain")) {
      response.status(415).json({
        code: "INVALID_CONTENT_TYPE",
        message: "텍스트 형식만 처리할 수 있습니다."
      });
      return;
    }

    const jobId = randomUUID();
    const reservation = queue.reserve(jobId);
    if (!reservation) {
      response.status(429).json({
        code: "QUEUE_FULL",
        message: PUBLIC_MESSAGES.QUEUE_FULL
      });
      return;
    }

    response.status(200);
    response.setHeader("Content-Type", "application/x-ndjson; charset=utf-8");
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("X-Accel-Buffering", "no");
    response.flushHeaders();
    const writer = new NdjsonWriter(response);
    writer.write({ type: "accepted", jobId, position: 0 });

    const clientController = new AbortController();
    let completed = false;
    let workspace: JobWorkspace | undefined;
    const startedAt = Date.now();
    const onDisconnect = (): void => {
      if (!completed) {
        clientController.abort();
        reservation.release();
      }
    };
    request.once("aborted", onDisconnect);
    response.once("close", onDisconnect);

    try {
      workspace = await JobWorkspace.create(config.runtimeRoot, jobId);
      await streamRequestBody(
        request,
        workspace.path("01_input.txt"),
        {
          minFreeBytes: config.minFreeBytes,
          signal: clientController.signal
        }
      );

      await reservation.submit(
        async queueSignal => {
          const signal = AbortSignal.any([
            clientController.signal,
            queueSignal
          ]);
          const result = await engine.transform({
            jobId,
            workspace: workspace!,
            signal,
            onEvent: event => writer.write(event)
          });
          writer.write({ type: "result-start" });
          await streamResult(writer, result.finalPath);
          writer.write({
            type: "done",
            sourceChars: result.sourceChars,
            outputChars: result.outputChars,
            chunks: result.chunks,
            elapsedMs: Date.now() - startedAt
          });
          logger.info({
            event: "transform_complete",
            jobId,
            sourceChars: result.sourceChars,
            outputChars: result.outputChars,
            chunks: result.chunks,
            elapsedMs: Date.now() - startedAt
          });
        },
        position => writer.write({ type: "queued", position })
      );
    } catch (error) {
      const event = publicEvent(error);
      writer.write(event);
      logger.error({
        event: "transform_failed",
        jobId,
        code: event.type === "error" ? event.code : "INTERNAL_ERROR",
        elapsedMs: Date.now() - startedAt
      });
    } finally {
      completed = true;
      request.off("aborted", onDisconnect);
      response.off("close", onDisconnect);
      reservation.release();
      await workspace?.cleanup();
      writer.end();
    }
  });

  app.use(express.static(path.join(config.projectRoot, "public"), {
    etag: true,
    maxAge: 0,
    setHeaders: response => response.setHeader("Cache-Control", "no-store")
  }));

  return app;
}
