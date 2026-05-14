# Telegram-бот для автопостинга парфюмерии из Ozon

MVP-сервис получает товары из Ozon Seller API, генерирует русскоязычный Telegram-пост через бесплатную локальную модель Ollama и отправляет черновик владельцу на подтверждение. После публикации товар помечается в SQLite, чтобы не появлялись дубли.

## Что есть в проекте

- загрузка товаров из Ozon Seller API;
- отдельная загрузка описаний, характеристик, цен и остатков, если методы доступны в вашем кабинете;
- генерация текста через Ollama (`qwen2.5:7b`, `llama3.1`, `mistral` или другая локальная модель);
- ручное подтверждение публикации в Telegram через inline-кнопки;
- списки товаров и черновиков прямо в Telegram;
- выбор конкретного товара для генерации поста;
- перегенерация и редактирование черновиков;
- исключение и возврат товаров в очередь;
- режим автопубликации по расписанию;
- защита от повторной публикации;
- Docker, `.env.example`, SQLite.

## Быстрый старт

1. Создайте Telegram-бота через [@BotFather](https://t.me/BotFather), добавьте его администратором в канал и разрешите публикацию сообщений.

2. Получите в личном кабинете Ozon `Client-Id` и `Api-Key`.

3. Установите Ollama и скачайте модель:

```powershell
ollama pull qwen2.5:7b
```

4. Создайте `.env` из примера:

```powershell
Copy-Item .env.example .env
```

5. Заполните `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_OWNER_ID=123456789
TELEGRAM_CHANNEL_ID=@your_channel
OZON_CLIENT_ID=...
OZON_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
APP_MODE=manual
DRY_RUN=true
```

`TELEGRAM_OWNER_ID` можно узнать у ботов вроде `@userinfobot`.

6. Установите зависимости и запустите:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

## Запуск через Docker

Если Ollama работает на хосте, для контейнера обычно нужно указать:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Затем:

```powershell
docker compose up --build
```

Если хотите использовать Ollama из `docker-compose.yml`, сначала поднимите сервис и скачайте модель внутрь контейнера:

```powershell
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b
docker compose up --build bot
```

## Команды владельца

- `/start` - список команд;
- `/status` - текущие настройки;
- `/sync` - загрузить товары из Ozon в локальную базу;
- `/run` - синхронизировать товары и подготовить пост;
- `/products [new|all|published|excluded] [страница]` - список товаров с кнопками;
- `/product <id>` - карточка товара и действия;
- `/draft [product_id]` - создать черновик для конкретного товара или следующего нового;
- `/drafts [pending|published|rejected|all] [страница]` - список черновиков;
- `/publish <draft_id>` - опубликовать черновик;
- `/edit <draft_id> <новый текст>` - заменить текст черновика;
- `/exclude <product_id>` - исключить товар из публикаций;
- `/include <product_id>` - вернуть товар в очередь.

У карточек и черновиков есть inline-кнопки:

- `Создать черновик`;
- `Опубликовать`;
- `Заново`;
- `Пропустить товар`;
- `Исключить`;
- `Вернуть в очередь`.

## Настройки

`APP_MODE=manual` - бот присылает черновик владельцу на подтверждение.

`APP_MODE=auto` - бот публикует следующий товар сам по расписанию.

`POST_STYLE` поддерживает значения:

- `info`;
- `selling`;
- `premium`;
- `short`;
- `long`.

`POST_INTERVAL_MINUTES` задает интервал автозапуска.

`DRY_RUN=true` полезен для теста: бот не публикует посты в канал, а присылает владельцу, что было бы отправлено.

## Важное про Ozon API

Клиент использует основные методы Seller API:

- `POST /v3/product/list`;
- `POST /v3/product/info/list`;
- `POST /v4/product/info/attributes`;
- `POST /v1/product/info/description`;
- `POST /v5/product/info/prices`, с fallback на `POST /v4/product/info/prices`;
- `POST /v4/product/info/stocks`.

Ozon иногда меняет состав полей и доступность методов по кабинетам. Поэтому нормализация данных собрана в [app/ozon_client.py](C:/Users/Seb0gf1/Documents/parfumes_bot/app/ozon_client.py): если в вашем кабинете другое поле для фото, цены, остатка или описания, обычно достаточно поправить этот файл.

## Принцип генерации

Промпт находится в [app/llm.py](C:/Users/Seb0gf1/Documents/parfumes_bot/app/llm.py). Он явно запрещает модели выдумывать ноты, бренд, объем, цену и свойства, которых нет в исходных данных. Это снижает риск вводящих в заблуждение постов, но перед публикацией все равно лучше использовать ручное подтверждение.

## Структура проекта

```text
app/
  bot.py           Telegram-команды и кнопки
  config.py        настройки из .env
  llm.py           генерация текста через Ollama
  main.py          точка входа и планировщик
  models.py        SQLite-модели
  ozon_client.py   Ozon Seller API
  repository.py    работа с базой
  service.py       бизнес-логика
```

## Проверка на нескольких товарах

1. Поставьте `APP_MODE=manual` и `DRY_RUN=true`.
2. Запустите бота.
3. Напишите боту `/sync`.
4. Откройте список товаров командой `/products`.
5. Выберите товар кнопкой или командой `/product <id>`.
6. Создайте черновик, проверьте текст и фото в личном чате с ботом.
7. Когда все устраивает, поставьте `DRY_RUN=false` и нажмите `Опубликовать`.
