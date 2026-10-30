# Configuración con cron (Linux / macOS)

Como alternativa al bucle `schedule` de `main.py`, puedes ejecutar el script una vez al día a las 12:00 mediante `cron`.

## 1. Edita tu crontab

```bash
crontab -e
```

## 2. Añade la siguiente línea

Ajusta las rutas a tu entorno (ruta absoluta al proyecto, al intérprete de Python y al archivo `.env`):

```cron
0 12 * * * /usr/bin/python3 /ruta/absoluta/al/proyecto/main.py >> /ruta/absoluta/al/proyecto/logs/buscador.log 2>&1
```

## 3. Variables de entorno

Asegúrate de que `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` estén disponibles para cron. Puedes exportarlas en el propio crontab o cargar un archivo `.env`:

```cron
0 12 * * * export TELEGRAM_BOT_TOKEN="tu_token"; export TELEGRAM_CHAT_ID="tu_chat_id"; /usr/bin/python3 /ruta/absoluta/al/proyecto/main.py >> /ruta/absoluta/al/proyecto/logs/buscador.log 2>&1
```

O más limpio, creando un pequeño wrapper shell que cargue `.env` antes de ejecutar Python.

## 4. Crear el directorio de logs

```bash
mkdir -p logs
```

## Notas

- Con cron no hace falta el `while True` de `main.py`: el script se ejecuta una vez y termina.
- Si usas el bucle `schedule`, no añadas la entrada de cron para evitar duplicados.
- Revisa periódicamente `logs/buscador.log` para detectar fallos de red o cambios en los selectores de las webs.
