# Deploy web panel

These files configure the web admin panel for `parfum.sebog1.ru`.

## Requirements

DNS:

```text
parfum.sebog1.ru A <SERVER_IP>
```

`.env`:

```env
WEB_HOST=127.0.0.1
WEB_PORT=9999
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=change_this_password
```

## Install service

```bash
cd /opt/tgchannelSeb
cd frontend
npm install
npm run build
cd ..
sudo cp deploy/tgchannelSeb-web.service /etc/systemd/system/tgchannelSeb-web.service
sudo systemctl daemon-reload
sudo systemctl enable tgchannelSeb-web
sudo systemctl restart tgchannelSeb-web
sudo systemctl status tgchannelSeb-web
```

If Node.js is missing:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node -v
npm -v
```

## Install Nginx proxy

```bash
sudo apt update
sudo apt install -y nginx
sudo cp /opt/tgchannelSeb/deploy/nginx-parfum.sebog1.ru.conf /etc/nginx/sites-available/parfum.sebog1.ru
sudo ln -sf /etc/nginx/sites-available/parfum.sebog1.ru /etc/nginx/sites-enabled/parfum.sebog1.ru
sudo nginx -t
sudo systemctl reload nginx
```

## HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d parfum.sebog1.ru
```

## Logs

```bash
journalctl -u tgchannelSeb-web -f
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```
