# Operations

## Ежедневно

- Проверить `harness:blocked` и `HARNESS_PAUSED`.
- Посмотреть `core / selftest` и `work / check-models`.
- Проверить usage/стоимость: `python scripts/usage.py --dir <artifact>`.
- Убедиться, что dispatch не пропускает cron (история `core / dispatch`).

## Ручные workflow

| Workflow | Когда |
|---|---|
| `core / dispatch` | запустить очередь вне cron |
| `core / publish` | повторить публикацию artifact (нужны target, issue, run_id, work_repo) |
| `core / resume` | снять pause и разблокировать задачи |
| `core / selftest` | тесты, config check, guard dry-run |
| `work / check-models` | smoke четырёх маршрутов |

Повтор publish вручную:

```bash
GH_TOKEN=... python scripts/notify.py \
  --repo OWNER/harness-core \
  --target sandbox --issue 12 --run-id 123456789 \
  --work-repo OWNER/harness-work
```

## Инциденты

| Симптом | Действие |
|---|---|
| Вторая ошибка подряд | issue -> `harness:blocked`, `HARNESS_PAUSED=true`; разобрать лог, затем `core / resume` |
| Post-merge verify упал | auto-revert PR + issue; проверить target и manifest |
| Revert не удался | harness ставит pause; вручную откатить main и разобрать |
| Модель 429/5xx | wrapper идёт по chain; проверить `work / check-models` |
| Все маршруты упали | issue `harness:failed`; смотреть `route-*.log` в artifact |
| Guard отклонил патч | issue `harness:failed`; при необходимости добавить `allow-tests`/`allow-deps` |
| Kernel PR ждёт approve | merge вручную, затем закрыть issue |
| Dry-run PR | проверить diff, выключить `HARNESS_DRY_RUN`, перезапустить publish |

## Переменные состояния

- `HARNESS_PAUSED` — `true` останавливает dispatch.
- `HARNESS_FAILURES` — число ошибок подряд; success сбрасывает в 0.
- `HARNESS_DRY_RUN` — `true` запрещает merge.

## Очистка

- Ветки `harness/issue-*` удаляются при ошибке publish; успешные ветки можно
  удалять после merge (GitHub делает это автоматически при настройке).
- Artifact `harness-output` хранится 7 дней.
- `HARNESS_PAUSED`/`HARNESS_FAILURES` можно сбросить `core / resume`.

## TODO phase 3

- egress allowlist для контейнера агента;
- scout;
- notifications;
- cost dashboard;
- multi-target onboarding.
