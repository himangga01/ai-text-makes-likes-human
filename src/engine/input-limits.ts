// One limit for pasted text and TXT/MD files, matching the DOCX/PPTX extracted
// text limit in engine_runtime/documents/model.py. Without it a single large
// input holds the only active queue slot for hours and spends the owner's quota.
export const MAX_INPUT_CHARS = 100_000;
// TXT/MD files are refused before they are read: 1 MiB holds 100,000 Korean
// characters in UTF-8 (about 300 KB) with room to spare.
export const MAX_TEXT_FILE_BYTES = 1024 * 1024;
// A UTF-8 code point takes at most 4 bytes, so a larger body cannot fit the limit.
export const MAX_INPUT_BYTES = MAX_INPUT_CHARS * 4;

// Served with the health payload so the web and desktop UIs check the same limits.
export const INPUT_LIMITS = { maxInputChars: MAX_INPUT_CHARS, maxTextFileBytes: MAX_TEXT_FILE_BYTES } as const;

/** Code points, after the LF normalization every path applies. */
export function inputChars(text: string): number {
  return Array.from(text.replace(/\r\n?/g, "\n")).length;
}
