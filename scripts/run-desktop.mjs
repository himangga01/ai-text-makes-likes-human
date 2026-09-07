import { createRequire } from "node:module";
import { spawn } from "node:child_process";
const require = createRequire(import.meta.url);
const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(require("electron"), ["desktop-dist/main.cjs"], { stdio: "inherit", env, windowsHide: true });
child.on("exit", code => process.exit(code ?? 1));
