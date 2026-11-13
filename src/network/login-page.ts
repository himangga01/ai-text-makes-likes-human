const ERRORS: Record<string, string> = {
  wrong: "비밀번호가 맞지 않습니다.",
  locked: "로그인 시도가 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
  unconfigured: "외부 접속 비밀번호가 아직 설정되지 않았습니다. 서버 PC에서 설정해 주세요."
};

/** The public address's sign-in page. No script (the CSP allows none inline) and fixed messages only. */
export function loginPage(configured: boolean, error: unknown): string {
  const message = configured ? (typeof error === "string" ? ERRORS[error] : undefined) : ERRORS.unconfigured;
  const disabled = configured ? "" : " disabled";
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<title>윤문 포털 로그인</title><link rel="stylesheet" href="/login.css"></head><body><main>`
    + `<h1>윤문 포털</h1><p>외부에서 접속하려면 비밀번호를 입력해 주세요.</p>`
    + (message ? `<p class="error" role="alert">${message}</p>` : "")
    + `<form method="post" action="/api/public-login"><label for="password">비밀번호</label>`
    + `<input id="password" name="password" type="password" autocomplete="current-password" required autofocus${disabled}>`
    + `<button type="submit"${disabled}>들어가기</button></form></main></body></html>`;
}
