/** Environment handed to the portal's child processes (the server under the service manager, the AI CLIs, Python).
 *
 * The portal is often started from an operator's terminal or an agent session, whose environment carries session
 * tokens, agent sockets and credential helpers (for example SSH_AUTH_SOCK, GIT_ASKPASS, CLAUDE_CODE_* or a terminal
 * app's hook tokens). None of them is needed to run a job, and a child that reads untrusted document text should not
 * be able to see them. So children receive an allowlist: what the operating system, the runtimes and the CLIs' own
 * sign-in need, plus this portal's settings. Anything else must be added here on purpose. */

const EXACT = new Set([
  // POSIX basics
  "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TMP", "TEMP", "TZ", "LANG", "LANGUAGE",
  "__CF_USER_TEXT_ENCODING",
  "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
  // Windows basics (names compare case-insensitively)
  "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
  "USERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
  "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "ALLUSERSPROFILE", "PUBLIC",
  "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
  // Network: proxies and corporate certificate stores
  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
  "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE",
  // The CLIs' own configuration and sign-in
  "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_OAUTH_TOKEN",
  // Python runtime selection that operators set on purpose
  "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"
]);

/** Prefixes kept whole: locale, this portal's own settings, and the providers' API settings. */
const PREFIXES = ["LC_", "HUMANIZE_", "SUPER_SEJONG_", "CODEX_", "OPENAI_", "ANTHROPIC_"];

export function isInheritedVariable(name: string): boolean {
  const upper = name.toUpperCase();
  return EXACT.has(upper) || PREFIXES.some(prefix => upper.startsWith(prefix));
}

/** The allowlisted part of `env`, with `extra` applied on top (extra values are always kept). */
export function childEnvironment(
  env: NodeJS.ProcessEnv = process.env,
  extra: NodeJS.ProcessEnv = {}
): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(env)) {
    if (value !== undefined && isInheritedVariable(name)) result[name] = value;
  }
  for (const [name, value] of Object.entries(extra)) {
    if (value !== undefined) result[name] = value;
  }
  return result;
}
