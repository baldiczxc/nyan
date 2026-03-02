# Инструкции по развертыванию (Deployment Setup)

Для развертывания проекта и обеспечения его бесперебойной работы 24/7 на Linux-сервере:

## 1. Переменные окружения

Добавьте следующие строки в ваш профиль (например, `.bashrc`) или экспортируйте их в конфигурации сервиса:

```env
export OPENROUTER_API_KEY="ваш_ключ_openrouter"
export ADMIN_BOT_TOKEN="токен_вашего_телеграм_бота_администратора"
export ADMIN_IDS="ВАШ_ТЕЛЕГРАМ_ID"
export CHANNELS_PATH="/абсолютный/путь/к/файлу/channels.json"
```

## 2. Docker сервисы

Запустите базу данных MongoDB:

```bash
docker-compose up -d mongodb
```

## 3. Сервисы Systemd (Рекомендуется для Python скриптов)

Создайте файлы сервисов в директории `/etc/systemd/system/`.

**Основной демон парсинга:** `/etc/systemd/system/nyan-daemon.service`

```ini
[Unit]
Description=Nyan News Daemon
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/абсолютный/путь/к/проекту
ExecStart=/usr/bin/python3 -m nyan.daemon --daemon-config-path configs/daemon_config.json
Restart=always
Environment="OPENROUTER_API_KEY=ВАШ_КЛЮЧ"

[Install]
WantedBy=multi-user.target
```

**Планировщик выжимок (8ч/24ч):** `/etc/systemd/system/nyan-summaries.service`

```ini
[Unit]
Description=Nyan News Summaries 8h/24h Scheduler
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/абсолютный/путь/к/проекту
ExecStart=/usr/bin/python3 -m scripts.run_summaries --mongo-config-path configs/mongo_config.json --client-config-path configs/client_config.json
Restart=always
Environment="OPENROUTER_API_KEY=ВАШ_КЛЮЧ"

[Install]
WantedBy=multi-user.target
```

**Телеграм-бот администратора:** `/etc/systemd/system/nyan-admin.service`

```ini
[Unit]
Description=Nyan News Admin Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/абсолютный/путь/к/проекту
ExecStart=/usr/bin/python3 scripts/admin_bot.py
Restart=always
Environment="ADMIN_BOT_TOKEN=ВАШ_ТОКЕН"
Environment="ADMIN_IDS=ВАШ_ID"

[Install]
WantedBy=multi-user.target
```

Включите и запустите сервисы:

```bash
sudo systemctl enable nyan-daemon nyan-summaries nyan-admin
sudo systemctl start nyan-daemon nyan-summaries nyan-admin
```
