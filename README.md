# 🚵‍♂️ Buscador de e-MTB de Ocasión

Script modular en Python para rastrear automáticamente tiendas profesionales de reacondicionado de bicicletas y encontrar ofertas de bicicletas eléctricas de montaña (e-MTB) doble suspensión que cumplan con filtros estrictos de talla, modalidad, peso, batería y precio.

Cuando encuentra una bicicleta con **Nota de Oportunidad ≥ 8.0/10**, la notifica por Telegram con un mensaje formateado en Markdown.

## Tabla de contenidos

- [¿Qué hace este proyecto?](#qué-hace-este-proyecto)
- [Requisitos estrictos de filtrado](#requisitos-estrictos-de-filtrado)
- [Algoritmo de Nota de Oportunidad (0-10)](#algoritmo-de-nota-de-oportunidad-0-10)
- [Integración con Telegram](#integración-con-telegram)
- [Automatización y programación](#automatización-y-programación)
- [Plataformas objetivo y garantía](#plataformas-objetivo-y-garantía)
- [Arquitectura modular](#arquitectura-modular)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Cómo usar](#cómo-usar)
- [Pruebas](#pruebas)
- [Advertencias importantes](#advertencias-importantes)
- [Roadmap / próximos pasos](#roadmap---próximos-pasos)
- [Licencia](#licencia)

---

## ¿Qué hace este proyecto?

Este script rastrea diariamente las secciones de e-MTB doble suspensión de cuatro tiendas profesionales de reacondicionado de bicicletas:

- **Bike Ocasión** (bike-ocasion.com)
- **Tuvalum** (tuvalum.com)
- **Buhobike** (buhobike.com)
- **Upway** (upway.es)

Para cada bicicleta encontrada aplica una serie de filtros estrictos y, si pasa, le asigna una **Nota de Oportunidad del 0 al 10**. Solo las bicicletas con nota **≥ 8.0** se guardan en una base de datos local SQLite y se envían por Telegram para evitar alertas duplicadas (salvo que bajen de precio).

La ejecución está programada para correr todos los días a las **12:00 de la mañana**.

---

## Requisitos estrictos de filtrado

| ID | Requisito | Detalle |
|----|-----------|---------|
| **S1** | Talla | Exclusivamente **Talla M** (aprox. 165 cm - 179 cm). |
| **S2** | Modalidad | **XC / Cross Country / Downcountry / Light e-MTB**. |
| **S3** | Peso | Máximo **19 kg** (se priorizan cuadros de carbono y motores ligeros; se descartan modelos > **21 kg**). |
| **S4** | Batería | Capacidad estrictamente **> 500 Wh** (ej. 540 Wh). |
| **S5** | Precio principal | Rango de **2.000 € a 3.000 €**. |
| **S6** | Precio excepcional | Si es una "oportunidad excepcional" (bici muy nueva, componentes tope de gama), el precio puede llegar hasta **3.300 €**. |

---

## Algoritmo de Nota de Oportunidad (0-10)

Cada bicicleta que pasa los filtros estrictos recibe una nota basada en cuatro criterios:

| Criterio | Peso máximo | Qué evalúa |
|----------|-------------|------------|
| Kilometraje | 2.5 | Premia < 2.000 km (+2.5); penaliza > 4.000 km (+0.5). |
| Calidad-precio | 3.0 | Cuadro de carbono, transmisión XT/AXS, suspensiones Kashima/Ultimate, precio en rango principal. |
| Motor | 2.5 | Marcas con diagnóstico claro (Shimano EP8/EP801, Bosch SX, Fazua, TQ, Mahle) y pocos kilómetros en el motor. |
| Precio excepcional | 2.0 | Precio dentro del rango principal o excepcional. |

**Total máximo: 10.0**

**Regla de salida (S8):** Solo se guardan y notifican bicicletas con nota final **≥ 8.0**.

---

## Integración con Telegram

El script usa la API de Telegram vía `requests` y envía un mensaje en **Markdown** con:

- Título de la bicicleta y precio.
- **Nota de Oportunidad destacada** (ej. 🔥 8.5/10).
- Kilómetros, capacidad de batería y material del cuadro.
- **Desglose breve** de por qué sacó esa nota.
- **Enlace directo de compra**.

Requiere configurar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el archivo `.env`.

---

## Automatización y programación

El script incluye un bucle con la librería `schedule` que se ejecuta todos los días exactamente a las **12:00**.

También se incluye el archivo `CRON.md` con las instrucciones exactas para configurar un **cronjob en Linux/Mac** como alternativa al bucle `while True`.

---

## Plataformas objetivo y garantía

El scraper está limitado **únicamente** a tiendas profesionales de reacondicionado que ofrecen por ley un mínimo de **1 año de garantía mecánica**:

- bike-ocasion.com
- tuvalum.com
- buhobike.com
- upway.es

**Bajo ningún concepto se incluye código para rastrear plataformas de trato entre particulares** como Wallapop, Milanuncios o foros, ya que no ofrecen garantía mecánica certificada.

---

## Arquitectura modular

El proyecto está separado en módulos con responsabilidad única:

| Archivo | Responsabilidad |
|---------|-----------------|
| `config.py` | Configuración central: URLs objetivo, filtros estrictos, credenciales Telegram, user-agents rotatorios, horario de ejecución. |
| `models.py` | Dataclass `Bicicleta` con todos los campos necesarios para scoring y notificación. |
| `db.py` | Base de datos SQLite: registro de bicicletas ya enviadas, deduplicación por ID y detección de bajadas de precio para re-alerta. |
| `evaluator.py` | Filtros estrictos (S1-S6) y algoritmo de Nota de Oportunidad 0-10 (S7, S8). |
| `notifier.py` | Notificador de Telegram vía `requests`, mensaje Markdown con todos los campos requeridos (S9). |
| `scraper_base.py` | Clase base con **tres capas de fallback** para obtener HTML: `curl_cffi` → `requests` → `Playwright`. Incluye reintentos, cabeceras rotatorias y manejo de excepciones de red. |
| `scrapers/bike_ocasion.py` | Adaptador específico para Bike Ocasión (selectores por ajustar tras inspección real). |
| `scrapers/tuvalum.py` | Adaptador específico para Tuvalum (selectores por ajustar tras inspección real). |
| `scrapers/buhobike.py` | Adaptador específico para Buhobike (selectores por ajustar tras inspección real). |
| `scrapers/upway.py` | Adaptador específico para Upway (selectores por ajustar tras inspección real). |
| `main.py` | Orquestador: scrape de los 4 sitios → filtros → scoring → base de datos → Telegram. Bucle de programación diaria a las 12:00. |
| `test_buscador.py` | Pruebas RED/GREEN con datos simulados para validar scoring, filtros, dedup y formateo de mensaje. |
| `CRON.md` | Instrucciones para ejecutar mediante cronjob en Linux/Mac. |
| `.env.example` | Plantilla de variables de entorno. |
| `requirements.txt` | Dependencias de Python. |

---

## Requisitos previos

- **Python 3.10 o superior** instalado en tu sistema.
- `pip` disponible en el PATH.
- Una cuenta de Telegram y un bot creado (vía [@BotFather](https://t.me/botfather)) para obtener `TELEGRAM_BOT_TOKEN`.
- El `chat_id` de tu chat de Telegram (puedes obtenerlo con [@userinfobot](https://t.me/userinfobot) o enviando un mensaje al bot y consultando `https://api.telegram.org/bot<TOKEN>/getUpdates`).

---

## Instalación

1. Cloná el repositorio:

```bash
git clone https://github.com/tu-usuario/buscador-bici-ocasion.git
cd buscador-bici-ocasion
```

2. Instalá las dependencias:

```bash
pip install -r requirements.txt
```

### Opcional: capas anti-baneo

Si los sitios bloquean el acceso (Cloudflare/JS), instalá una o ambas capas adicionales:

```bash
# Capa 1 (recomendada para empezar): curl_cffi
pip install curl_cffi

# Capa 3 (más robusta si hay Cloudflare fuerte): Playwright
pip install playwright
playwright install chromium
```

El `scraper_base.py` intenta automáticamente `curl_cffi`, luego `requests`, y finalmente `Playwright` si las primeras fallan.

---

## Configuración

1. Copiá el archivo de ejemplo:

```bash
cp .env.example .env
```

2. Editá `.env` y completá tus credenciales:

```ini
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
# Opcional: ruta personalizada de la base de datos SQLite
# BUSCADOR_DB_PATH=bicis_enviadas.db
```

---

## Cómo usar

### Opción A: Ejecución manual con bucle diario (schedule)

```bash
python main.py
```

El script quedará corriendo y ejecutará la búsqueda todos los días a las 12:00. Presioná `Ctrl+C` para detenerlo.

### Opción B: Cronjob (Linux / Mac)

Consultá el archivo `CRON.md` para la configuración exacta. Ejemplo de entrada en crontab:

```cron
0 12 * * * /usr/bin/python3 /ruta/absoluta/al/proyecto/main.py >> /ruta/absoluta/al/proyecto/logs/buscador.log 2>&1
```

---

## Pruebas

El proyecto incluye `test_buscador.py` con pruebas RED/GREEN usando datos simulados (no depende de la web real ni de credenciales de Telegram). Valida:

- Filtros estrictos (talla, modalidad, batería, peso, precio).
- Algoritmo de Nota de Oportunidad.
- Deduplicación de SQLite y re-alerta por bajada de precio.
- Formateo del mensaje de Telegram.

Ejecutá:

```bash
python test_buscador.py
```

Deberías ver: `Todas las pruebas pasaron (GREEN).`

---

## Advertencias importantes

1. **Selectores CSS son placeholders.** Los archivos en `scrapers/` contienen selectores genéricos (ej. `.product-item`, `article.product`) que **deben ajustarse** tras inspeccionar el HTML real de cada web con el inspector del navegador (F12). Sin este paso, el scraper no extraerá datos correctamente.

2. **Protecciones anti-baneo.** Las 4 tiendas objetivo probablemente usen Cloudflare o renderizado JavaScript. `requests` por sí solo puede recibir 403 Forbidden. Por eso `scraper_base.py` incluye capas de fallback con `curl_cffi` y `Playwright`. Probá cuál funciona en tu entorno.

3. **Datos inferidos.** Peso, talla, batería y motor a menudo no vienen como campos directos en el listado. Es posible que tengas que entrar al detalle de cada producto o inferirlos del título/descripción.

4. **No se rastrea a particulares.** El proyecto está limitado estrictamente a las 4 tiendas profesionales listadas. No incluyas Wallapop, Milanuncios ni foros.

---

## Roadmap / próximos pasos

- [ ] Instalar Python y dependencias en tu máquina local.
- [ ] Ejecutar `python test_buscador.py` y verificar que pase todo (GREEN).
- [ ] Inspeccionar el HTML de una tarjeta de producto en cada una de las 4 webs y pegar el fragmento aquí para completar los selectores CSS reales.
- [ ] Probar el scraping real sitio por sitio.
- [ ] Configurar `.env` con tu bot de Telegram y probar el envío de mensajes.
- [ ] Automatizar con `main.py` o cron según `CRON.md`.

---

## Estado actual del proyecto

| Tarea | Estado | Detalle |
|-------|--------|---------|
| `config.py` | ✅ Hecho | URLs de los 4 sitios, filtros S1-S6, credenciales Telegram, user-agents, horario 12:00. |
| `requirements.txt` + `.env.example` | ✅ Hecho | Dependencias y plantilla de variables de entorno. |
| `models.py` | ✅ Hecho | Dataclass `Bicicleta` con todos los campos para scoring y Telegram. |
| `db.py` | ✅ Hecho | SQLite: dedup por ID, no reenvía salvo bajada de precio. |
| `evaluator.py` | ✅ Hecho | Filtros estrictos S1-S6 y algoritmo de Nota de Oportunidad 0-10 (S7, S8). |
| `notifier.py` | ✅ Hecho | Telegram vía `requests`, mensaje Markdown con todos los campos (S9). |
| `scraper_base.py` | ✅ Hecho | Tres capas de fallback: `curl_cffi` → `requests` → `Playwright`. Reintentos y manejo de errores de red. |
| `scrapers/` (4 sitios) | ⚠️ Placeholders | Selectores CSS genéricos. **Deben ajustarse** tras inspeccionar el HTML real de cada web. |
| `main.py` | ✅ Hecho | Orquestador + bucle `schedule` diario a las 12:00 (S10). |
| `CRON.md` | ✅ Hecho | Instrucciones para cronjob Linux/Mac. |
| `test_buscador.py` | ✅ Hecho | Pruebas RED/GREEN con datos simulados. |
| `README.md` | ✅ Hecho | Documentación completa (este archivo). |

---

## Por dónde vamos

El próximo paso inmediato es **completar los selectores CSS reales de al menos un sitio** para que el scraper extraiga datos de verdad.

Para eso necesitás:

1. Entrá a una de las 4 webs (ej. `https://www.bike-ocasion.com/bicicletas-electronicas/de-montana-doble-suspension/`).
2. Presioná **F12** → pestaña **Inspector de elementos**.
3. Buscá una tarjeta de producto (un `<article>` o `<div>` que contenga título, precio y enlace).
4. Hacé clic derecho → **Copiar** → **Copiar elemento** (o "Copiar HTML externo").
5. Pegá ese HTML acá (en el issue o PR del repositorio) para que complete los selectores exactos de ese scraper.

Una vez tengamos los selectores reales de un sitio, probamos el scraping real y pasamos al siguiente.

---

## Qué falta hacer

| # | Tarea | Por qué falta |
|---|-------|---------------|
| 1 | **Instalar Python y dependencias** en tu máquina local | Este entorno no tiene Python instalado; las pruebas y el scraping real corren en tu PC. |
| 2 | **Ejecutar `python test_buscador.py`** | Valida que la lógica de scoring, filtros, dedup y mensaje Telegram funcione con datos simulados. |
| 3 | **Ajustar selectores CSS** en `scrapers/*.py` | Los placeholders actuales no extraerán datos reales hasta que coincidan con el HTML de cada web. |
| 4 | **Probar scraping real sitio por sitio** | Verificar que `curl_cffi`, `requests` o `Playwright` logren obtener HTML de cada tienda. |
| 5 | **Configurar `.env`** con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` | Necesario para recibir notificaciones por Telegram. |
| 6 | **Probar envío de Telegram** con una bici simulada | Confirmar que el mensaje Markdown llega bien a tu chat. |
| 7 | **Automatizar con `main.py` o cron** | Dejarlo corriendo todos los días a las 12:00. |

---

## Licencia

MIT

---

## Créditos

Desarrollado como asistente de código bajo la identidad **el Gentleman** (Pi-specific coding-agent harness), siguiendo el flujo de desarrollo **Organic Driven Development (ODD)**.
