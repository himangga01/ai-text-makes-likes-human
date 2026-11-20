/** Office (DOCX/PPTX) limits on the TypeScript side. The file size is checked here before any bytes reach
 * Python (portal upload, app import, MCP server). The package and text limits (expanded size, compression
 * ratio, XML nodes and depth, text, paragraphs, model batches) are checked in engine_runtime/documents
 * (package.py, model.py); an over-limit file fails there with a DocumentLimitError, which the Gateway prints
 * with this code, so the portal, the app, the MCP server and the skill all name it the same way. */
export const MAX_OFFICE_FILE_BYTES = 50 * 1024 ** 2;
export const OFFICE_LIMIT_CODE = 'DOCUMENT_TOO_LARGE';
export const OFFICE_FILE_TOO_LARGE = '파일은 50 MiB 이하만 지원합니다.';

/** A refused Office file. The message is fixed Korean text from this module or from Python, never document
 * content or a path, so every surface shows it as it is. */
export class DocumentLimitError extends Error {
  readonly code = OFFICE_LIMIT_CODE;
}
