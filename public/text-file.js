export class TextFileError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "TextFileError";
    this.code = code;
  }
}

export function decodeTextBytes(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (view[0] === 0xef && view[1] === 0xbb && view[2] === 0xbf) {
    return {
      text: new TextDecoder("utf-8", { fatal: true }).decode(view.subarray(3)),
      encoding: "UTF-8"
    };
  }
  if (view[0] === 0xff && view[1] === 0xfe) {
    return {
      text: new TextDecoder("utf-16le", { fatal: true }).decode(view.subarray(2)),
      encoding: "UTF-16LE"
    };
  }
  if (view[0] === 0xfe && view[1] === 0xff) {
    return {
      text: new TextDecoder("utf-16be", { fatal: true }).decode(view.subarray(2)),
      encoding: "UTF-16BE"
    };
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
      throw new TextFileError(
        "TEXT_FILE_DECODE_FAILED",
        "텍스트 파일을 읽지 못했습니다. 다른 인코딩으로 저장해 다시 시도해 주세요."
      );
    }
  }
}

export async function readTextFile(file) {
  if (!(file instanceof File) || !file.name.toLowerCase().endsWith(".txt")) {
    throw new TextFileError(
      "INVALID_TEXT_FILE",
      "TXT 파일만 불러올 수 있습니다."
    );
  }
  const decoded = decodeTextBytes(await file.arrayBuffer());
  return { ...decoded, fileName: file.name };
}
