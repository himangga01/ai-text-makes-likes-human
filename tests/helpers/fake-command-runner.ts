import type {
  CommandRequest,
  CommandResult,
  CommandRunner
} from "../../src/process/command-runner.js";

export class FakeCommandRunner implements CommandRunner {
  readonly calls: CommandRequest[] = [];

  constructor(private readonly results: Array<CommandResult | Error>) {}

  async run(request: CommandRequest): Promise<CommandResult> {
    this.calls.push(request);
    const result = this.results.shift();
    if (!result) {
      throw new Error("No fake command result configured");
    }
    if (result instanceof Error) {
      throw result;
    }
    return result;
  }
}

export function exited(
  stdout: string,
  exitCode = 0,
  stderr = ""
): CommandResult {
  return { exitCode, stdout, stderr, termination: "exit" };
}
