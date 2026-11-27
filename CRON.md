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

- Con `main.py --once` el script ejecuta un único barrido completo y termina (ideal para `cron` o Programador de tareas de Windows).
- Si usas el bucle `schedule`, no añadas la entrada programada del sistema para evitar duplicados.
- Revisa periódicamente `logs/buscador.log` para detectar fallos de red o cambios en los selectores de las webs.

---

# Configuración en Windows Task Scheduler (PowerShell)

Para programar la ejecución diaria a las **12:00** en Windows despertando el equipo de la suspensión (`WakeToRun`) y recuperando ejecuciones pendientes (`StartWhenAvailable`):

```powershell
$action = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument "main.py --once" `
    -WorkingDirectory "G:\Proyectos OpenCode\Buscador BiciOcasion"

$trigger = New-ScheduledTaskTrigger -Daily -At 12:00

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName "BuscadorBiciOcasion" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Búsqueda diaria de e-MTB de ocasión y envío de Top 3 a Telegram" `
    -Force
```

## Operación intensiva Black Friday / Cyber Monday (`--modo-caza`, cada 2 h)

Durante campañas clave se puede registrar una tarea paralela temporal `BuscadorBiciOcasion_BlackFriday` sin alterar el cron diario de las `12:00`, ejecutando `main.py --once --modo-caza` (caché de fichas reducida a 45 min, lock de concurrencia `cache/buscador.lock` y supresión de envíos repetidos si no hay cambios reales):

```powershell
$actionCaza = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument "main.py --once --modo-caza" `
    -WorkingDirectory "G:\Proyectos OpenCode\Buscador BiciOcasion"

$triggerCaza = New-ScheduledTaskTrigger `
    -Once -At ([datetime]"2026-11-26T23:55:00") `
    -RepetitionInterval (New-TimeSpan -Hours 2) `
    -RepetitionDuration (New-TimeSpan -Days 5)

# Tope explícito al 01/12/2026 01:00 (cubre Black Friday + Cyber Monday)
$triggerCaza.EndBoundary = "2026-12-01T01:00:00"

$settingsCaza = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName "BuscadorBiciOcasion_BlackFriday" `
    -Action $actionCaza `
    -Trigger $triggerCaza `
    -Settings $settingsCaza `
    -Description "Caza Black Friday y Cyber Monday (--modo-caza cada 2h hasta 01/12/2026 01:00)" `
    -Force
```

> Nota 1: al mantener `BuscadorBiciOcasion` (12:00) y `BuscadorBiciOcasion_BlackFriday` en paralelo, el archivo lock atómico `cache/buscador.lock` (stale timeout 15 min) evita solapamientos si coinciden en el mismo minuto.
> Nota 2: en Windows con el alias de Microsoft Store (`AppData\Local\Microsoft\WindowsApps\python.exe`), conviene pasar en `-Execute` la ruta directa del intérprete real (por ejemplo `C:\Users\alvar\AppData\Local\Python\pythoncore-3.15-64\python.exe`, tal como quedó registrado en producción) y entrecomillar `"G:\Proyectos OpenCode\Buscador BiciOcasion\main.py" --once --modo-caza` en `-Argument`.
> Nota 3: `WakeToRun` solo reactiva el equipo desde **Modo de espera (S3)** (no desde apagado completo `Shutdown Off` / S5). Si el PC estuvo apagado durante la noche o acumuló `NumberOfMissedRuns > 0` al encenderlo, conviene lanzar manualmente `python main.py --once --modo-caza` para cubrir las franjas perdidas sin esperar al siguiente tick cada 2 h.

### Limpieza post-campaña (después del `01/12/2026 01:00`)

Una vez expirado `EndBoundary` tras Cyber Monday (`01/12/2026`), puedes deshabilitar o eliminar la tarea temporal manteniendo intacta `BuscadorBiciOcasion`:

```powershell
Unregister-ScheduledTask -TaskName "BuscadorBiciOcasion_BlackFriday" -Confirm:$false
```
