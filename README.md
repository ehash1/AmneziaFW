# Скрипт настройки межсетевого экрана для Amnezia VPN

Скрипт предназначен для настройки межсетевого экрана Amnezia VPN по белому или черному списку для протоколов WireGuard и SOCKS5.

## Режимы работы

1. **Белый список для всех сетей** - доступ только к сайтам из whitelist.txt
2. **Белый список только для SOCKS5** - ограничения только для SOCKS5, WireGuard без ограничений
3. **Черный список для всех сетей** - блокировка только сайтов из blacklist.txt
4. **Черный список только для SOCKS5** - блокировка только для SOCKS5, WireGuard без ограничений
5. **Сброс всех правил** - полное восстановление доступа

## Установка

```bash
git clone https://github.com/yourusername/amnezia-vpn-firewall.git
cd amnezia-vpn-firewall
chmod +x firewall.sh
```

## Файлы списков (должны лежать рятом со скриптом)

**whitelist.txt** - разрешённые сайты:
```
google.com
yandex.ru
github.com
```

**blacklist.txt** - заблокированные сайты:
```
facebook.com
youtube.com
instagram.com
```

## Запуск

```bash
# Запуск с портами по умолчанию (33287 - SOCKS5, 38604 - WireGuard)
sudo ./firewall.sh

# Запуск с пользовательскими портами
sudo ./firewall.sh 1080 51820
```

## Сохранение правил после перезагрузки

```bash
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```
