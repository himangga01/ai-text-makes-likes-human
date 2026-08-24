function clampProgress(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, value));
}

function chunkPosition(event) {
  const total = Number(event.total);
  const current = Number(event.current);

  return {
    total: Number.isFinite(total) && total > 0 ? total : 1,
    current: Number.isFinite(current) ? current : 1
  };
}

export function progressForEvent(event) {
  switch (event?.type) {
    case "accepted":
      return 2;
    case "queued":
      return null;
    case "progress": {
      switch (event.phase) {
        case "sanitize":
          return 5;
        case "chunk":
          return 15;
        case "transform": {
          const { current, total } = chunkPosition(event);
          return clampProgress(15 + 55 * ((current - 1) / total));
        }
        case "verify": {
          const { current, total } = chunkPosition(event);
          return clampProgress(15 + 55 * ((current - 0.5) / total));
        }
        case "assemble":
          return 90;
        default:
          return undefined;
      }
    }
    case "result-start":
    case "result-delta":
      return 95;
    case "done":
      return 100;
    default:
      return undefined;
  }
}
