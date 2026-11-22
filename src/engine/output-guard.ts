import { EngineError } from "./errors.js";

/** The CLIs see more than our prompt: Claude Code, for one, puts the signed-in account's e-mail address in every
 * session's context. A document crafted to make the model copy such details into its "rewrite" would hand them to
 * whoever submitted it. A rewrite never needs an address the prompt did not contain, so a reply that introduces one
 * is refused as invalid output. */
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/gu;

/** Every string in a JSON reply (escape sequences decoded), or the raw text when it is not JSON. */
function replyText(raw: string): string {
  const strings: string[] = [];
  const collect = (value: unknown): void => {
    if (typeof value === "string") strings.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  try { collect(JSON.parse(raw)); } catch { return raw; }
  return strings.join("\n");
}

export function assertNoForeignEmail(prompt: string, raw: string, label: string): void {
  const known = new Set((prompt.normalize("NFKC").match(EMAIL) ?? []).map(value => value.toLowerCase()));
  const text = replyText(raw).normalize("NFKC");
  for (const match of text.match(EMAIL) ?? []) {
    if (!known.has(match.toLowerCase())) {
      throw new EngineError("ENGINE_OUTPUT_INVALID", false, `${label} reply contains an e-mail address that is not in the source`);
    }
  }
}
