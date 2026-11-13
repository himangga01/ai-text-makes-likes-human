import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig } from "../config.js";
import { publicAuthPath, writePublicPassword } from "../network/public-auth.js";

/** Sets the password the portal asks on its public address: `node dist/ops/public-password.js`.
 * A terminal gets a hidden prompt (asked twice); otherwise the first line of stdin is used. */
const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function ask(prompt: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const input = process.stdin;
    let value = "";
    process.stdout.write(prompt);
    input.setRawMode(true);
    input.resume();
    input.setEncoding("utf8");
    const onData = (chunk: string) => {
      for (const char of chunk) {
        if (char === "\u0003") { cleanup(); process.stdout.write("\n"); reject(new Error("취소했습니다.")); return; }
        if (char === "\r" || char === "\n") { cleanup(); process.stdout.write("\n"); resolve(value); return; }
        if (char === "\u007f" || char === "\b") value = value.slice(0, -1);
        else value += char;
      }
    };
    const cleanup = () => { input.off("data", onData); input.setRawMode(false); input.pause(); };
    input.on("data", onData);
  });
}

async function readLine(): Promise<string> {
  let text = "";
  for await (const chunk of process.stdin) text += String(chunk);
  return text.split(/\r?\n/u)[0] ?? "";
}

async function main(): Promise<void> {
  const file = publicAuthPath(loadConfig(process.env, projectRoot).runtimeRoot);
  let password: string;
  if (process.stdin.isTTY) {
    password = await ask("외부 주소 비밀번호: ");
    if (await ask("한 번 더: ") !== password) throw new Error("두 번 입력한 비밀번호가 다릅니다.");
  } else password = await readLine();
  if (password.length < 4) throw new Error("비밀번호는 4자 이상이어야 합니다.");
  await writePublicPassword(file, password);
  console.log(`저장했습니다: ${file}`);
  console.log("외부 주소에 로그인돼 있던 브라우저는 모두 다시 로그인해야 합니다.");
  if (password.length < 10) console.log("참고: 10자보다 짧은 비밀번호입니다. 로그인 실패는 시간당 10번까지만 받습니다.");
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
