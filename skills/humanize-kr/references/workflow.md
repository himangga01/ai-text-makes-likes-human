# Gateway 실행 절차

`skillRoot`는 현재 SKILL.md의 부모다. Windows에서는 `$python = Join-Path $skillRoot 'python/python.exe'`, `$gateway = Join-Path $skillRoot 'engine_runtime/skill_gateway.py'`로 잡고 `& $python $gateway ...`를 사용한다. 본문을 명령 인자에 넣지 않는다. 원문·결과·JSON 쓰기는 UTF-8을 사용한다.

1. 사용자가 파일을 제공했다면 그 TXT/MD를 사용한다. 대화로 원문을 제공했다면 고유한 임시 `.txt` 파일에 원문을 그대로 기록한다. 만들어진 파일만 나중에 정리한다.
2. `prepare --input <원문 파일>`을 실행한다. JSON의 job, sourceHash, status를 보관한다. Gateway 기본 작업 위치는 사용자 TEMP의 `humanize-kr-skills`다.
3. `status: rewrite`이면 inputPath에 있는 청크와 rulesPath의 규칙을 읽는다. 사실·주장·수치·고유명사·직접 인용·제목·문단 순서·말투·Markdown 표식을 보존하고 번역투만 다듬는다. 새로운 사실·비유·예시를 추가하지 않는다. attempt가 2이면 더 보수적으로 편집한다.
4. responsePath에 아래 JSON을 기록한다. 원문 이외의 해설이나 코드 펜스를 rewrittenText에 넣지 않는다. warnings는 최대 20개, 각 300자 이하이며 없으면 빈 배열이다.

```json
{"rewrittenText":"윤문한 전체 청크","warnings":[]}
```

5. `accept --job <job> --chunk <chunk> --attempt <attempt> --source-hash <sourceHash> --response <responsePath>`를 실행한다. Gateway가 주는 다음 status·chunk·attempt를 그대로 따른다. 이전 attempt나 다른 job의 출력을 재사용하지 않는다. 재시도 한도·원문 복원 정책을 스킬이 바꾸지 않는다.
6. 모든 청크가 끝나 `ready-to-finalize`가 되면, 원본과 다른 **새 출력 경로**를 정해 `finalize --job <job> --output <새 결과.md>`를 실행한다. 기본 이름은 `<원본이름>-humanized.md`이며 파일이 이미 있으면 새 번호를 붙인다. 실패를 무시하거나 검증 전 출력물을 최종 결과로 제공하지 않는다.
7. `done`의 outputPath에 생성된 결과를 제공하고 warnings의 검토·원문 복원 사항을 함께 알린다. 최종 텍스트를 다시 임의로 고치지 않는다.
8. `cleanup --job <job>`으로 해당 작업만 지운다. 오류·취소 때도 알 수 있는 자신의 job에 한해 cleanup을 시도한다. 사용자 입력·결과 파일이나 TEMP 전체를 지우지 않는다.

중단 후에는 `next --job <job>`으로 다음 청크를 확인할 수 있다. 원문 hash/manifest가 달라졌거나 operation.lock 충돌이 있으면 진행 중인 다른 호출이 끝났는지 확인한다. 모르는 lock을 지우거나 state 파일을 편집해 검사를 우회하지 않는다. 해결되지 않으면 해당 작업을 실패로 보고하고 새 원문 작업으로 시작한다.

장문은 next가 가리키는 청크만 읽는다. 한 번에 전체 문서를 대화에 다시 붙여 넣지 않는다. 입력 길이에 맞춰 여러 번 accept하고 마지막에 전체 문서 검증을 거친다.
