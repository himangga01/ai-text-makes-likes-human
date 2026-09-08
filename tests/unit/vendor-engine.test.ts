import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve("vendor/humanize-engine");
const required = [
  "scripts/prepare_monolith_input.py",
  "scripts/sanitize_text.py",
  "scripts/verify_gates.py",
  "scripts/verify_change_rate.py",
  "scripts/checks.py",
  "scripts/reassemble_chunks.py",
  "scripts/restore_modality.py",
  "scripts/strip_injected_commas.py",
  "scripts/console.py",
  "scripts/build_quick_rules.py",
  "scripts/build_diagnosis_rules.py",
  "skills/humanize-korean/references/quick-rules.md",
  "skills/humanize-korean/references/quick-rules.header.md",
  "skills/humanize-korean/references/quick-rules.footer.md",
  "skills/humanize-korean/references/diagnosis-rules.md",
  "skills/humanize-korean/references/ai-tell-taxonomy.md",
  "skills/humanize-korean/references/rewriting-playbook.md",
  "skills/humanize-korean/references/metrics.py",
  "skills/humanize-korean/references/metrics_v2.py",
  "skills/humanize-korean/references/baseline.json",
  "skills/humanize-korean/references/baseline_v2.json",
  "LICENSE"
];

describe("vendored humanize engine", () => {
  it("contains the pinned v2.3.2 runtime", async () => {
    await Promise.all(required.map(file => stat(path.join(root, file))));
    const version = await readFile(path.join(root, "ENGINE_VERSION"), "utf8");

    expect(version).toBe(
      "version=2.3.2\ncommit=9747f036cdc28a1a8aea4dc71fef1f7846eb96f7\n"
    );
  });
});
