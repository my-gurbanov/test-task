# Асинхронный процессинг платежей

Сервис принимает платежи по HTTP. Воркер эмулирует работу платёжного шлюза и отправляет результат на webhook клиента.

## Запуск

```sh
just run
```

Compose поднимает PostgreSQL, RabbitMQ, `api` и `consumer`. Alembic применяет миграции перед запуском. FastAPI слушает `127.0.0.1:8000`. 
Отдельный процесс `consumer` публикует события из outbox и обрабатывает их через FastStream. 
Для локального запуска ключ по умолчанию `local-payment-key`. 
Переопределить его можно через `API_KEY` в окружении или `.env`.

## API

Создать платёж:

```sh
curl -i http://127.0.0.1:8000/api/v1/payments \
  -H 'X-API-Key: local-payment-key' \
  -H 'Idempotency-Key: order-123' \
  -H 'Content-Type: application/json' \
  -d '{"amount":"19.50","currency":"EUR","description":"Order 123","metadata":{"order_id":123},"webhook_url":"https://example.com/payments"}'
```

Подставьте URL получателя, доступного из контейнера `api`. Поддерживаются HTTP и HTTPS. Пример ответа `202 Accepted`:

```json
{"payment_id":"759cb596-67d9-47e1-9eb1-35215b686ba3","status":"pending","created_at":"2026-11-19T10:00:00Z"}
```

Получить актуальные данные о платеже:

```sh
curl -i http://127.0.0.1:8000/api/v1/payments/759cb596-67d9-47e1-9eb1-35215b686ba3 \
  -H 'X-API-Key: local-payment-key'
```

## Проверки

```sh
just lint
just test
```

`just lint` применяет исправления Ruff и запускает ty и flake8. Для него нужны Python 3.15 и uv. `just test` запускает pytest в том же образе, что API и консьюмер, в отдельном Compose-проекте с PostgreSQL и RabbitMQ. После прогона проект удаляется. GitHub Actions запускает обе команды на push и pull request. Если Ruff изменил файлы, проверка CI падает.
