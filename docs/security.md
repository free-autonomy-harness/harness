# Security

## Модель прав

- GitHub App `harness-bot`, не PAT. Токены downscope по job через
  `actions/create-github-app-token`.
- `work/agent`: `contents:read`; контейнер не получает GitHub-токен.
- `work/notify`: только dispatch `core/publish`.
- `core/publish`: единственный write/merge.
- Branch protection: PR + `harness/verify` + родной CI + squash, direct push запрещён.
- App permissions: Contents RW, PR RW, Issues RW, Statuses RW, Checks R,
  Actions RW, Workflows RW (для kernel PR), Metadata R.

## Патч

- Одноразовый clone target на base SHA.
- Рабочее дерево копируется без `.git`; hooks/external diff не участвуют.
- `git add -A; git diff --cached --binary`.
- Guard:
  - deny `.env*`, `*.pem`, `*.key`, `id_*`;
  - deny `.github/workflows/**` в target (в core — kernel approval);
  - tests/deps только с `allow-tests`/`allow-deps` (tests в core разрешены);
  - symlinks, submodules, binary, файлы > 1 МБ;
  - max 300 файлов / 2 МБ патча / 20k строк;
  - gitleaks по дереву (v8.30.1 в publish workflow);
  - kernel paths core -> `requires_approval`, PR без auto-merge.

## Ключи моделей

- Ключи лежат только в GitHub Secrets `harness-work`.
- Wrapper передаёт в контейнер только ключ текущего маршрута через env-file
  mode 0600; файл удаляется после запуска.
- В логах ключи редактируются.
- Остаточный риск: контейнер с ключом имеет сеть и может слить ключ.
  Phase 3: egress allowlist.

## Проверки

- Verify запускается в отдельной копии дерева, чтобы тесты не попали в патч.
- Post-merge verify идёт на main; ошибка -> revert PR.
- Две ошибки подряд -> `harness:blocked` + pause.
- Kernel PR требуют ручного merge; CODEOWNERS дублирует это на уровне GitHub.

## TODO

- [ ] phase 2: egress allowlist не реализован (phase 3).
- [ ] phase 3: подпись/аттестация артефактов, если понадобится.
