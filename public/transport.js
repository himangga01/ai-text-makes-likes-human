export const desktop = Boolean(window.humanizeDesktop);

export async function health() {
  if (desktop) return window.humanizeDesktop.health();
  const response = await fetch("/api/health", { cache: "no-store" });
  return response.json();
}

export async function transform(text, engine, signal, onEvent, settings) {
  if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
  if (desktop) {
    let failure;
    const unsubscribe = window.humanizeDesktop.onEvent(event => {
      if (failure) return;
      try { onEvent(event); } catch (error) { failure = error; }
    });
    const cancel = () => window.humanizeDesktop.cancel().catch(() => {});
    signal.addEventListener("abort", cancel, { once: true });
    try {
      await window.humanizeDesktop.transform({ text, engine, settings });
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
      if (failure) throw failure;
    } finally { unsubscribe(); signal.removeEventListener("abort", cancel); }
    return;
  }
  const query=new URLSearchParams({engine,...(settings?{model:settings.model,effort:settings.effort}:{})});
  const response = await fetch(`/api/transform?${query}`, {
    method: "POST", headers: { "content-type": "text/plain; charset=utf-8" }, body: text, signal
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.message || "변환 요청을 시작하지 못했습니다.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
      for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
      if (done) break;
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
