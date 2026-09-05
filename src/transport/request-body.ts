import { open, statfs, unlink } from "node:fs/promises";
import path from "node:path";
import type { Readable } from "node:stream";
import { EngineError } from "../engine/errors.js";

const DEFAULT_CHECK_INTERVAL = 16 * 1024 * 1024;

export interface StreamRequestOptions {
  minFreeBytes: number;
  signal: AbortSignal;
  getFreeBytes?: (directory: string) => Promise<number>;
  checkEveryBytes?: number;
}

export interface StreamRequestResult {
  bytes: number;
  chars: number;
}

async function systemFreeBytes(directory: string): Promise<number> {
  const stats = await statfs(directory);
  return Number(stats.bavail) * Number(stats.bsize);
}

function aborted(): EngineError {
  return new EngineError(
    "CLIENT_ABORTED",
    true,
    "The client cancelled the request"
  );
}

const CR = 0x0d;
const LF = 0x0a;

interface NewlineState {
  pendingCr: boolean;
}

// The engine, the model, and the browser textarea all speak LF. CRLF or bare
// CR input would desynchronise the Python chunk offsets (computed on LF text)
// from the bytes on disk, so line endings are normalised while streaming.
// CR and LF bytes never occur inside multi-byte UTF-8 sequences, so this is
// safe to do before decoding and across arbitrary chunk boundaries.
function normalizeNewlines(chunk: Buffer, state: NewlineState): Buffer {
  const output = Buffer.allocUnsafe(chunk.byteLength);
  let length = 0;
  for (const byte of chunk) {
    if (byte === CR) {
      output[length++] = LF;
      state.pendingCr = true;
      continue;
    }
    if (byte === LF && state.pendingCr) {
      state.pendingCr = false;
      continue;
    }
    state.pendingCr = false;
    output[length++] = byte;
  }
  return output.subarray(0, length);
}

async function removePartial(destination: string): Promise<void> {
  try {
    await unlink(destination);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

export async function streamRequestBody(
  readable: Readable,
  destination: string,
  options: StreamRequestOptions
): Promise<StreamRequestResult> {
  const getFreeBytes = options.getFreeBytes ?? systemFreeBytes;
  const checkEveryBytes = options.checkEveryBytes ?? DEFAULT_CHECK_INTERVAL;
  const directory = path.dirname(destination);
  let handle: Awaited<ReturnType<typeof open>> | undefined;

  try {
    if (options.signal.aborted) throw aborted();
    if ((await getFreeBytes(directory)) < options.minFreeBytes) {
      throw new EngineError(
        "INSUFFICIENT_DISK",
        true,
        "Insufficient disk space for request body"
      );
    }

    handle = await open(destination, "wx", 0o600);
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let bytes = 0;
    let chars = 0;
    let hasNonWhitespace = false;
    let nextDiskCheck = checkEveryBytes;
    const newlines: NewlineState = { pendingCr: false };

    for await (const value of readable) {
      if (options.signal.aborted) throw aborted();
      const chunk = normalizeNewlines(
        typeof value === "string" ? Buffer.from(value, "utf8") : Buffer.from(value),
        newlines
      );

      let offset = 0;
      while (offset < chunk.byteLength) {
        const { bytesWritten } = await handle.write(
          chunk,
          offset,
          chunk.byteLength - offset,
          null
        );
        offset += bytesWritten;
      }

      bytes += chunk.byteLength;
      const decoded = decoder.decode(chunk, { stream: true });
      chars += Array.from(decoded).length;
      hasNonWhitespace ||= /\S/u.test(decoded);

      if (bytes >= nextDiskCheck) {
        if ((await getFreeBytes(directory)) < options.minFreeBytes) {
          throw new EngineError(
            "INSUFFICIENT_DISK",
            true,
            "Insufficient disk space while receiving request body"
          );
        }
        nextDiskCheck = bytes + checkEveryBytes;
      }
    }

    if (options.signal.aborted) throw aborted();
    const finalDecoded = decoder.decode();
    chars += Array.from(finalDecoded).length;
    hasNonWhitespace ||= /\S/u.test(finalDecoded);

    await handle.close();
    handle = undefined;

    if (!hasNonWhitespace) {
      throw new EngineError("EMPTY_INPUT", false, "Input is empty");
    }

    return { bytes, chars };
  } catch (error) {
    await handle?.close();
    await removePartial(destination);
    if (error instanceof EngineError) throw error;
    throw new EngineError(
      "INTERNAL_ERROR",
      false,
      "Unable to receive a valid UTF-8 request body",
      { cause: error }
    );
  }
}
