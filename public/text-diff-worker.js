import { diffText } from "./text-diff.js";

export function runDiffJob(message) {
  if (message?.type !== "diff") return null;
  return {
    type: "result",
    generation: message.generation,
    result: diffText(message.source, message.target, message.options)
  };
}

if (typeof self !== "undefined" && typeof self.addEventListener === "function") {
  self.addEventListener("message", event => {
    try {
      const response = runDiffJob(event.data);
      if (response) self.postMessage(response);
    } catch (error) {
      self.postMessage({
        type: "error",
        generation: event.data?.generation,
        message: error instanceof Error ? error.message : String(error)
      });
    }
  });
}
