# Корневой сертификат Минцифры

`russian_trusted_root_ca.pem` — корневой сертификат удостоверяющего центра Министерства
цифрового развития. Он **публичный**, не секрет, и лежит в репозитории осознанно.

## Зачем

Цепочка MAX: `*.max.ru` ← `Russian Trusted Sub CA` ← `Russian Trusted Root CA`.
Этого корня нет в наборе certifi, поэтому в контейнере `python:3.12-slim` запрос к
`platform-api2.max.ru` падает на проверке сертификата. На Windows проходит — корень есть в
хранилище системы, и из-за этого проблему легко не заметить до развёртывания.

Промежуточный сертификат класть не нужно: сервер присылает его сам, проверка корнем проходит.

## Происхождение

Источник: <https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt>
(страница выдачи — <https://www.gosuslugi.ru/crt>).

| | |
|---|---|
| Субъект | `C=RU, O=The Ministry of Digital Development and Communications, CN=Russian Trusted Root CA` |
| Отпечаток SHA-256 | `D26D2D0231B7C39F92CC738512BA54103519E4405D68B5BD703E9788CA8ECF31` |
| Действителен до | 27.02.2032 |

Отпечаток закреплён константой в `tests/test_bot_tls.py`. Если файл подменят или повредят,
тест упадёт сразу, а не запрос в контейнере посреди ночи.

## Как проверить самому

```bash
openssl s_client -connect platform-api2.max.ru:443 -servername platform-api2.max.ru \
  -CAfile russian_trusted_root_ca.pem </dev/null 2>/dev/null | grep "Verify return code"
# Verify return code: 0 (ok)
```
