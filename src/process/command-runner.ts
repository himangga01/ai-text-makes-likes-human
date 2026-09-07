import { spawn } from "node:child_process";

export type CommandTermination = "exit" | "timeout" | "aborted";

export interface CommandRequest {
  command: string;
  args: string[];
  cwd: string;
  stdin?: string;
  timeoutMs: number;
  signal?: AbortSignal;
  env?: NodeJS.ProcessEnv;
}

export interface CommandResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  termination: CommandTermination;
}

export interface CommandRunner {
  run(request: CommandRequest): Promise<CommandResult>;
}

function terminateProcessTree(pid: number): void {
  if (process.platform === "win32") {
    const killer = spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], {
      shell: false,
      windowsHide: true,
      stdio: "ignore"
    });
    killer.unref();
    return;
  }

  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // The child already exited between the state check and termination.
    }
  }
}

export class SpawnCommandRunner implements CommandRunner {
  constructor(private readonly onProcess?: (pid: number, alive: boolean) => void) {}
  run(request: CommandRequest): Promise<CommandResult> {
    return new Promise((resolve, reject) => {
      if (request.signal?.aborted) {
        resolve({
          exitCode: -1,
          stdout: "",
          stderr: "",
          termination: "aborted"
        });
        return;
      }

      const child = spawn(request.command, request.args, {
        cwd: request.cwd,
        shell: false,
        windowsHide: true,
        detached: process.platform !== "win32",
        env: request.env ?? process.env,
        stdio: ["pipe", "pipe", "pipe"]
      });

      if (child.pid !== undefined) this.onProcess?.(child.pid, true);
      child.once("close", () => { if (child.pid !== undefined) this.onProcess?.(child.pid, false); });
      let stdout = "";
      let stderr = "";
      let termination: CommandTermination = "exit";
      let terminationStarted = false;

      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", chunk => {
        stdout += String(chunk);
      });
      child.stderr.on("data", chunk => {
        stderr += String(chunk);
      });

      const terminate = (reason: Exclude<CommandTermination, "exit">): void => {
        if (terminationStarted) return;
        terminationStarted = true;
        termination = reason;
        if (child.pid !== undefined) {
          terminateProcessTree(child.pid);
        }
      };

      const timer = setTimeout(() => terminate("timeout"), request.timeoutMs);
      const onAbort = (): void => terminate("aborted");
      request.signal?.addEventListener("abort", onAbort, { once: true });

      const cleanup = (): void => {
        clearTimeout(timer);
        request.signal?.removeEventListener("abort", onAbort);
      };

      child.on("error", error => {
        cleanup();
        reject(error);
      });
      child.on("close", code => {
        cleanup();
        resolve({
          exitCode: code ?? (termination === "exit" ? 3 : -1),
          stdout,
          stderr,
          termination
        });
      });

      child.stdin.on("error", () => {
        // A fast-failing child may close stdin before the parent writes it.
      });
      child.stdin.end(request.stdin ?? "");
    });
  }
}
