export class TextFileError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "TextFileError";
    this.code = code;
  }
}

const DECODE_FAILED_MESSAGE = "텍스트 파일을 읽지 못했습니다. 다른 인코딩으로 저장해 다시 시도해 주세요.";

function decodeMarked(view, label, offset, encoding) {
  try {
    return { text: new TextDecoder(label, { fatal: true }).decode(view.subarray(offset)), encoding };
  } catch {
    throw new TextFileError("TEXT_FILE_DECODE_FAILED", DECODE_FAILED_MESSAGE);
  }
}

export function decodeTextBytes(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (view[0] === 0xef && view[1] === 0xbb && view[2] === 0xbf) return decodeMarked(view, "utf-8", 3, "UTF-8");
  if (view[0] === 0xff && view[1] === 0xfe) return decodeMarked(view, "utf-16le", 2, "UTF-16LE");
  if (view[0] === 0xfe && view[1] === 0xff) return decodeMarked(view, "utf-16be", 2, "UTF-16BE");
  // BOM-less UTF-16 decodes as valid UTF-8 full of NULs; refuse it instead of guessing.
  if (view.includes(0)) {
    throw new TextFileError(
      "TEXT_FILE_UNSUPPORTED_ENCODING",
      "BOM이 없는 UTF-16 등 지원하지 않는 인코딩입니다. UTF-8로 저장해 다시 시도해 주세요."
    );
  }
  try {
    return {
      text: new TextDecoder("utf-8", { fatal: true }).decode(view),
      encoding: "UTF-8"
    };
  } catch {
    try {
      return {
        text: new TextDecoder("euc-kr", { fatal: true }).decode(view),
        encoding: "CP949/EUC-KR"
      };
    } catch {
      throw new TextFileError("TEXT_FILE_DECODE_FAILED", DECODE_FAILED_MESSAGE);
    }
  }
}

function formatFromFileName(fileName) {
  const normalized = String(fileName).toLowerCase();
  if (normalized.endsWith(".md")) return "markdown";
  if (normalized.endsWith(".txt")) return "text";
  return null;
}

export function getMarkdownDownloadName(fileName) {
  const baseName = String(fileName).replace(/\.md$/i, "").trim();
  return baseName ? `${baseName}-humanized.md` : "humanized.md";
}

// The save dialog must never propose the source file itself.
export function getTextDownloadName(fileName) {
  const baseName = String(fileName ?? "").replace(/\.txt$/i, "").trim();
  return baseName ? `${baseName}-humanized.txt` : "humanized.txt";
}

// Same values as src/engine/input-limits.ts; the server's health payload overrides them.
export const DEFAULT_INPUT_LIMITS = { maxInputChars: 100_000, maxTextFileBytes: 1024 * 1024 };

export function inputLimitMessage(limits = DEFAULT_INPUT_LIMITS) {
  return `원문은 ${limits.maxInputChars.toLocaleString("ko-KR")}자 이하만 변환할 수 있습니다. 나눠서 변환해 주세요.`;
}

export async function readTextFile(file, limits = DEFAULT_INPUT_LIMITS) {
  const format = file instanceof File ? formatFromFileName(file.name) : null;
  if (!format) {
    throw new TextFileError(
      "INVALID_TEXT_FILE",
      "TXT 또는 MD 파일만 불러올 수 있습니다."
    );
  }
  // Checked before reading: a huge file would otherwise freeze the page while it loads.
  if (file.size > limits.maxTextFileBytes) {
    const mebibytes = (limits.maxTextFileBytes / 1024 ** 2).toLocaleString("ko-KR");
    throw new TextFileError("TEXT_FILE_TOO_LARGE", `TXT·MD 파일은 ${mebibytes} MiB 이하만 불러올 수 있습니다.`);
  }
  const decoded = decodeTextBytes(await file.arrayBuffer());
  if (Array.from(decoded.text.replace(/\r\n?/g, "\n")).length > limits.maxInputChars) {
    throw new TextFileError("TEXT_TOO_LONG", inputLimitMessage(limits));
  }
  return { ...decoded, fileName: file.name, format };
}
