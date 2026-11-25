# Установка на VPS

Пошагово: от чистого VPS (на примере Beget) до Whatever по HTTPS на своём домене,
с файрволом, резервными копиями и обновлением. Общие сведения об эксплуатации —
в [operations.md](operations.md).

Итоговая схема:

```
браузер ──HTTPS──▶ nginx на сервере (80/443, Let's Encrypt)
                     └──▶ 127.0.0.1:8080 ──▶ docker compose: frontend → backend → postgres
```

Наружу открыты только SSH, 80 и 443. Порт приложения 8080 слушает только 127.0.0.1.

## 1. Сервер

В панели Beget: **VPS → Создать сервер**.

- Образ: **Ubuntu 24.04**. Если в маркетплейсе есть готовый образ «Docker» на Ubuntu 24.04,
  берите его, тогда шаг 3 сводится к проверке версии.
- Конфигурация: от 2 ядер, 2–4 ГБ памяти, от 30 ГБ диска. Этого хватает на 100 одновременных
  участников (см. «Нагрузка» в operations.md); диск уходит на базу, файлы досок и копии.
- SSH-ключ: добавьте свой публичный ключ при создании, если панель это предлагает.
  Ключ на своём компьютере создаётся так: `ssh-keygen -t ed25519`, публичная часть —
  в `~/.ssh/id_ed25519.pub`.

Запишите IP-адрес сервера из панели.

## 2. Вход по SSH и пользователь

```bash
ssh root@IP_СЕРВЕРА
```

Обновите систему и заведите пользователя для работы (дальше всё — от него):

```bash
apt update && apt -y upgrade
apt -y install git make curl ufw
adduser deploy                                # спросит пароль: он нужен для sudo
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/  # ваш ключ — и для deploy
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
```

Проверьте в **новом** окне терминала, что `ssh deploy@IP_СЕРВЕРА` пускает по ключу. Только
после этого отключите вход по паролю и вход root:

```bash
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

Если памяти 2 ГБ, добавьте файл подкачки: сборке фронтенда на сервере может не хватить памяти.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. Docker

Если выбран образ с Docker, только проверьте версии. Иначе установите:

```bash
curl -fsSL https://get.docker.com | sudo sh
```

Если `get.docker.com` или `download.docker.com` недоступны с сервера, поставьте Docker
из репозитория Ubuntu:

```bash
sudo apt -y install docker.io docker-compose-v2
```

Затем:

```bash
sudo usermod -aG docker deploy                # docker без sudo; перезайдите по SSH
docker --version
docker compose version                        # нужна 2.20 или новее
```

Если `docker pull` отвечает ошибкой 403, 429 или зависает (Docker Hub бывает недоступен
из российских сетей), подключите зеркало и перезапустите Docker:

```bash
echo '{ "registry-mirrors": ["https://mirror.gcr.io"] }' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

## 4. Код

Репозиторий приватный, поэтому серверу нужен свой ключ только для чтения (deploy key):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_ho -N ""
cat ~/.ssh/github_ho.pub
```

Добавьте выведенную строку на GitHub: репозиторий **ho → Settings → Deploy keys →
Add deploy key**, галочку «Allow write access» не ставьте. Затем:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    IdentityFile ~/.ssh/github_ho
EOF
git clone git@github.com:smesherlu23-cmd/ho.git ~/whatever
cd ~/whatever
```

Если репозиторий публичный, ключ не нужен: `git clone https://github.com/smesherlu23-cmd/ho.git ~/whatever`.

## 5. Настройки

```bash
cp .env.example .env
chmod 600 .env                                # в файле пароль базы
openssl rand -hex 24                          # скопируйте: это пароль базы
nano .env
```

Задайте в `.env`:

```bash
POSTGRES_PASSWORD=строка_из_openssl
WHATEVER_BIND_ADDRESS=127.0.0.1               # 8080 — только для nginx на этом сервере
WHATEVER_COOKIE_SECURE=true                   # вход только по HTTPS
WHATEVER_TRUSTED_PROXY=172.16.0.0/12          # nginx сервера, как его видит контейнер
WHATEVER_BACKUP_DIR=/home/deploy/backups      # куда сервис backup кладёт копии
```

Остальные настройки можно не трогать, их описание — в `.env.example`. Пароль базы
задаётся один раз: с ним PostgreSQL создаёт базу при первом запуске.

## 6. Запуск

```bash
docker compose up -d --build --wait           # первая сборка — 5–10 минут
docker compose ps                             # все сервисы running/healthy, migrate — exited (0)
curl -s http://127.0.0.1:8080/api/health      # {"status":"ok",...}
docker compose exec backend python -m app.cli create-admin admin --name "Имя Фамилия"
```

Последняя команда спросит пароль администратора дважды. Остальные учётные записи
администратор создаёт в интерфейсе, в разделе «Пользователи».

Если `--wait` завершился ошибкой, причина — в `docker compose logs migrate` или
`docker compose logs backend`.

## 7. Домен и HTTPS

**DNS.** В панели, где куплен домен (в Beget — раздел **DNS**), создайте A-запись
домена или поддомена (например, `board.example.ru`) на IP сервера. Проверка с сервера
или своего компьютера: `dig +short board.example.ru` должен вернуть этот IP. Обычно
запись начинает работать за 5–30 минут.

**nginx и сертификат.** Готовая настройка — [ops/nginx/whatever.conf](../ops/nginx/whatever.conf):
WebSocket, загрузка больших файлов, долгие соединения.

```bash
sudo apt -y install nginx certbot python3-certbot-nginx
sudo cp ops/nginx/whatever.conf /etc/nginx/sites-available/whatever.conf
sudo sed -i 's/whatever.example.ru/board.example.ru/' /etc/nginx/sites-available/whatever.conf
sudo ln -s /etc/nginx/sites-available/whatever.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d board.example.ru --redirect -m ваша@почта --agree-tos
```

certbot получит сертификат Let's Encrypt, допишет его в настройку и включит
перенаправление с HTTP на HTTPS. Продлевает сертификат он сам по таймеру; проверка:
`sudo certbot renew --dry-run`.

Откройте `https://board.example.ru` и войдите под администратором. Создайте доску и
откройте её во втором окне: изменения должны появляться сразу, это работает WebSocket.

## 8. Файрвол

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'                   # 80 и 443
sudo ufw enable
sudo ufw status
```

Порты, которые публикует Docker, ufw не закрывает: Docker пишет свои правила в обход
него. Поэтому порт 8080 закрыт настройкой `WHATEVER_BIND_ADDRESS=127.0.0.1` (шаг 5),
а не файрволом. Проверка со своего компьютера: `curl -m 5 http://IP_СЕРВЕРА:8080`
должен завершиться ошибкой соединения.

## 9. Резервные копии

Сервис `backup` уже работает: каждый день в 3:00 по Москве копирует базу и файлы досок
в `WHATEVER_BACKUP_DIR` и хранит копии 14 дней. Проверьте сразу:

```bash
make backup
sudo ls -l /home/deploy/backups
```

Копия на том же сервере не спасёт, если пропадёт сам сервер. Забирайте копии в другое
место, например на свой компьютер или другой сервер по cron:

```bash
rsync -a --delete deploy@IP_СЕРВЕРА:/home/deploy/backups/ ~/whatever-backups/
```

Файлы копий принадлежат root, поэтому для rsync от deploy дайте ему право чтения:
`sudo setfacl -R -m u:deploy:rX -m d:u:deploy:rX /home/deploy/backups` (пакет `acl`).
Подойдёт и облачное хранилище S3 (у Beget оно есть) через `rclone`.

Восстановление из копии: `make restore BACKUP=whatever-2026-11-23T0000`
(подробно — в operations.md, «Восстановление»).

## 10. Обновление

```bash
cd ~/whatever
make backup                                   # копия перед обновлением
git pull
docker compose up -d --build --wait --remove-orphans
```

Миграции базы применятся сами до старта нового бэкенда. Что изменилось и нужно ли
что-то сделать при обновлении — в [CHANGELOG.md](../CHANGELOG.md).

Обновления безопасности Ubuntu ставит сама (`unattended-upgrades` включён по умолчанию);
раз в месяц стоит выполнить `sudo apt update && sudo apt upgrade` и перезагрузить сервер.
Приложение после перезагрузки поднимется само (`restart: unless-stopped`).

## Если что-то не работает

| Признак | Причина и что делать |
| --- | --- |
| Доска не синхронизируется, в консоли браузера ошибка WebSocket | nginx сервера не передаёт `Upgrade`: проверьте, что используется `ops/nginx/whatever.conf`, `sudo nginx -t` |
| Картинка больше 1 МБ не загружается, ошибка 413 | в настройке nginx нет `client_max_body_size 0` |
| Вход не проходит, после ввода пароля снова форма входа | сайт открыт по HTTP при `WHATEVER_COOKIE_SECURE=true`: откройте по HTTPS |
| Действия отклоняются с 403 «Запрос с чужого сайта отклонён» | прокси меняет `Host`: в настройке должно быть `proxy_set_header Host $host` |
| Сборка падает с `Killed` или `exit code 137` | не хватает памяти: добавьте подкачку (шаг 2) |
| `docker pull` — 403, 429 или зависание | зеркало реестра (шаг 3) |
| Сервис не становится healthy | `docker compose logs <сервис>`; неверная настройка в `.env` указана в журнале backend |
