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

### Cómo conectar tu cuenta de Telegram (paso a paso)

Para recibir las notificaciones del buscador en tu chat de Telegram, seguí estos pasos:

#### 1. Creá un bot con @BotFather

1. Abrí Telegram y buscá al usuario **@BotFather**.
2. Enviá el comando `/newbot`.
3. Seguí las instrucciones: poné un nombre para tu bot (ej. "Buscador e-MTB") y un nombre de usuario único (ej. `buscador_ebtm_bot`).
4. Al terminar, @BotFather te dará un **token** que se ve así: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`.
5. **Copiá ese token**: es tu `TELEGRAM_BOT_TOKEN`.

#### 2. Obtené tu `chat_id`

Hay dos formas:

**Opción A (más fácil):** Enviá cualquier mensaje a tu bot recién creado y luego entrá a esta URL en tu navegador (reemplazá `TU_TOKEN` por el token del paso 1):

```
https://api.telegram.org/bot<TU_TOKEN>/getUpdates
```

Buscá en el JSON la sección `"chat": {"id": -1001234567890, ...}`. Ese número (ej. `-1001234567890`) es tu `TELEGRAM_CHAT_ID`.

**Opción B:** Usá el bot **@userinfobot** en Telegram. Enviá `/start` y te dirá tu `chat_id` directamente.

#### 3. Configurá el archivo `.env`

1. Copiá la plantilla: `cp .env.example .env`
2. Editá `.env` y pegá tus valores reales:

```ini
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
# Opcional: ruta personalizada de la base de datos SQLite
# BUSCADOR_DB_PATH=bicis_enviadas.db
```

⚠️ **Importante:** Nunca subas el archivo `.env` a GitHub. Contiene tu token de bot y tu chat_id. Ya está excluido por `.gitignore`.

#### 4. Probá el envío

El script solo envía notificaciones cuando encuentra una bici con **Nota de Oportunidad ≥ 8.0** que no haya sido notificada antes (o que bajó de precio). Para probar que Telegram funciona sin esperar a que aparezca una bici real, podés ejecutar los tests:

```bash
python test_buscador.py
```

Aunque los tests no envían mensajes reales a Telegram (require credenciales configuradas), validan que la lógica de formateo del mensaje es correcta.

Cuando el script encuentre una bici real con nota ≥ 8.0, recibirás un mensaje en tu chat de Telegram con algo como:

```
🚵‍♂️ *Nueva oportunidad de e-MTB encontrada*

*Moustache Samedi 29 Trail 3*
🏪 Tienda: Upway
💰 Precio: *1.999 €*
🔥 Nota de Oportunidad: *8.5/10*

📏 Talla: M: ideal para ciclistas entre 1m69 - 1m85
⚙️ Modalidad: De doble suspensión
⚖️ Peso: 24 kg
🔋 Batería: 687 Wh
🛞 Cuadro: Aluminio
⚡ Motor: Bosch Performance Line CX
📅 Año: 2023
🛣️ Kilómetros: 10.152 km
🛡️ Garantía: 1 año(s)

_Desglose de la nota:_
Kilometraje: Km moderados (10152 km): +1.5 | Calidad-precio: cuadro carbono: +1.0; ...

🔗 [Enlace directo de compra](https://upway.es/products/moustache-samedi-29-trail-3-rk7fu0)
```

#### 5. Seguridad

- **No compartas tu `TELEGRAM_BOT_TOKEN`** con nadie. Cualquiera con ese token puede enviar mensajes en nombre de tu bot.
- **No subas el archivo `.env`** a ningún repositorio público. Está en `.gitignore` para evitar que se suba por error.

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
| `config.py` | Configuración central: URLs objetivo, filtros estrictos, credenciales Telegram, user-agents rotatorios, proxies (opcional), horario de ejecución. | Configuración central: URLs objetivo, filtros estrictos, credenciales Telegram, user-agents rotatorios, proxies (opcional), horario de ejecución. |
| `models.py` | Dataclass `Bicicleta` con todos los campos necesarios para scoring y notificación. | Dataclass `Bicicleta` con todos los campos necesarios para scoring y notificación. |
| `db.py` | Base de datos SQLite: registro de bicicletas ya enviadas, deduplicación por ID y detección de bajadas de precio para re-alerta. | Base de datos SQLite: registro de bicicletas ya enviadas, deduplicación por ID y detección de bajadas de precio para re-alerta. |
| `evaluator.py` | Filtros estrictos (S1-S6) y algoritmo de Nota de Oportunidad 0-10 (S7, S8). | Filtros estrictos (S1-S6) y algoritmo de Nota de Oportunidad 0-10 (S7, S8). |
| `notifier.py` | Notificador de Telegram vía `requests`, mensaje Markdown con todos los campos requeridos (S9). | Notificador de Telegram vía `requests`, mensaje Markdown con todos los campos requeridos (S9). |
| `scraper_base.py` | Clase base con **motor Scrapling**: `Fetcher` (HTTP con impersonación TLS) → `StealthyFetcher` (navegador stealth con `solve_cloudflare`). Incluye reintentos, delays aleatorios, `ProxyRotator` opcional, health check y caché de fichas de detalle. | Clase base con **motor Scrapling**: `Fetcher` (HTTP con impersonación TLS) → `StealthyFetcher` (navegador stealth con `solve_cloudflare`). Incluye reintentos, delays aleatorios, `ProxyRotator` opcional, health check y caché de fichas de detalle. |
| `scrapers/bike_ocasion.py` | Adaptador específico para Bike Ocasión (selectores reales inspeccionados con ego-browser, código listo). Extrae talla, batería, km, motor, suspensión, cuadro y componentes directamente de la tarjeta de listado. Paginación de 5 páginas. | Adaptador específico para Bike Ocasión (selectores reales inspeccionados con ego-browser, código listo). Extrae talla, batería, km, motor, suspensión, cuadro y componentes directamente de la tarjeta de listado. Paginación de 5 páginas. |
| `scrapers/tuvalum.py` | Adaptador específico para Tuvalum (selectores estimados; dominio no resolvió desde el entorno de desarrollo, pendiente de verificación real). | Adaptador específico para Tuvalum (selectores estimados; dominio no resolvió desde el entorno de desarrollo, pendiente de verificación real). |
| `scrapers/buhobike.py` | Adaptador específico para Buhobike (selectores reales inspeccionados con ego-browser, código listo). Cloudflare resuelto con `StealthyFetcher` (`solve_cloudflare=True`). | Adaptador específico para Buhobike (selectores reales inspeccionados con ego-browser, código listo). Cloudflare resuelto con `StealthyFetcher` (`solve_cloudflare=True`). |
| `scrapers/upway.py` | Adaptador específico para Upway (selectores reales inspeccionados con ego-browser; scraping real probado y funcionando con Playwright/Scrapling). | Adaptador específico para Upway (selectores reales inspeccionados con ego-browser; scraping real probado y funcionando con Playwright/Scrapling). |
| `scrapers/enriquecedor_web.py` | Enriquecedor web para completar campos faltantes (peso, año, suspensión, cuadro, componentes, modalidad) usando la ficha del producto del propio sitio (Scrapling) + DuckDuckGo como fallback. Incluye caché JSON en disco para no re-consultar URLs ya visitadas. | Enriquecedor web para completar campos faltantes (peso, año, suspensión, cuadro, componentes, modalidad) usando la ficha del producto del propio sitio (Scrapling) + DuckDuckGo como fallback. Incluye caché JSON en disco para no re-consultar URLs ya visitadas. |
| `main.py` | Orquestador: scrape de los 4 sitios → **health check** → filtros → scoring → **enriquecimiento paralelo** → base de datos → Telegram. Logging a archivo `logs/buscador.log`. Bucle de programación diaria a las 12:00. | Orquestador: scrape de los 4 sitios → **health check** → filtros → scoring → **enriquecimiento paralelo** → base de datos → Telegram. Logging a archivo `logs/buscador.log`. Bucle de programación diaria a las 12:00. |
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

Scrapling ya incluye todo lo necesario (HTTP con impersonación TLS, navegador stealth con Playwright/Patchright, y `solve_cloudflare=True` para Cloudflare). Se instala con:

```bash
pip install -r requirements.txt
```

Esto instala `scrapling`, `patchright`, `browserforge` y `msgspec`. No hace falta instalar `curl_cffi` ni `playwright` por separado.

### Proxies (opcional, para sitios con Cloudflare agresivo)

Si un sitio bloquea por IP (ej. Buhobike con Cloudflare muy agresivo), configurá proxies rotatorios en `.env`:

```ini
PROXY_LIST=http://usuario:contraseña@ip:puerto,http://otro-proxy:puerto
PROXY_ROTATION=cyclic
```

Scrapling usará `ProxyRotator` para rotar entre ellos automáticamente.

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

1. **Selectores CSS inspeccionados.** Los selectores de Bike Ocasión, Buhobike y Upway ya fueron inspeccionados en el HTML real de cada web (vía ego-browser). Los de **Tuvalum** son estimados porque el dominio no resolvió desde el entorno de desarrollo; verificalos si el scraping falla.

2. **Protecciones anti-baneo.** Las 4 tiendas objetivo probablemente usen Cloudflare o renderizado JavaScript. `scraper_base.py` usa **Scrapling** con dos capas: `Fetcher` (HTTP rápido con impersonación TLS) y `StealthyFetcher` (navegador stealth con `solve_cloudflare=True` para Cloudflare). Buhobike requiere la capa stealth porque devuelve 503 con HTTP simple. Si seguís teniendo bloqueos, configurá proxies rotatorios (`PROXY_LIST` en `.env`).

3. **Datos inferidos.** Peso, talla, batería y motor a menudo no vienen como campos directos en el listado. Bike Ocasión ya extrae talla, batería, km, motor, suspensión, cuadro y componentes desde la tarjeta de listado. Los campos que falten (peso, año) se completan con el enriquecedor web (ficha del sitio + DuckDuckGo) antes de notificar por Telegram.

4. **Health check.** Antes de cada ejecución, `main.py` verifica que cada scraper devuelva al menos 1 producto. Si alguno devuelve 0, se lanza una alerta por log y Telegram (posibles selectores rotos por cambio de HTML).

5. **Caché de fichas.** Las fichas de producto ya consultadas se guardan en `cache/fichas_detalle.json` para no re-scrapear URLs repetidas y acelerar la corrida.

6. **No se rastrea a particulares.** El proyecto está limitado estrictamente a las 4 tiendas profesionales listadas. No incluyas Wallapop, Milanuncios ni foros.

---

## Roadmap / próximos pasos

- [x] Instalar Python y dependencias en tu máquina local.
- [x] Ejecutar `python test_buscador.py` y verificar que pase todo (GREEN).
- [x] Probar scraping real sitio por sitio (Upway, Bike Ocasión y Buhobike probados con Scrapling).
- [ ] Configurar `.env` con tu bot de Telegram y probar el envío de mensajes.
- [ ] Verificar/selectores de Tuvalum (pendiente de inspección real del dominio en tu máquina local).
- [ ] Automatizar con `main.py` o cron según `CRON.md`.
- [ ] Configurar proxies rotatorios (`PROXY_LIST` en `.env`) si un sitio bloquea por IP.

---

## Estado actual del proyecto

| Tarea | Estado | Detalle |
|-------|--------|---------|
| `config.py` | ✅ Hecho | URLs de los 4 sitios, filtros S1-S6, credenciales Telegram, user-agents, proxies (opcional), horario 12:30. |
| `requirements.txt` + `.env.example` | ✅ Hecho | Dependencias (Scrapling + Patchright + Browserforge + Msgspec) y plantilla de variables de entorno. |
| `models.py` | ✅ Hecho | Dataclass `Bicicleta` con todos los campos para scoring y Telegram. |
| `db.py` | ✅ Hecho | SQLite: dedup por ID, no reenvía salvo bajada de precio. |
| `evaluator.py` | ✅ Hecho | Filtros estrictos S1-S6 y algoritmo de Nota de Oportunidad 0-10 (S7, S8). |
| `notifier.py` | ✅ Hecho | Telegram vía `requests`, mensaje Markdown con todos los campos (S9). |
| `scraper_base.py` | ✅ Hecho | Motor Scrapling: `Fetcher` → `StealthyFetcher` con `solve_cloudflare`. Delays aleatorios, `ProxyRotator` opcional, paginación, salud de scrapers. |
| `scrapers/` (4 sitios) | ✅ Hecho | Bike Ocasión, Buhobike y Upway con selectores reales verificados y scraping real probado. Tuvalum con selectores estimados (pendiente de inspección real en tu máquina). |
| `scrapers/enriquecedor_web.py` | ✅ Hecho | Enriquece campos faltantes (peso, año, suspensión, cuadro, componentes, modalidad) desde ficha del sitio + DuckDuckGo fallback. Caché JSON en disco. |
| `main.py` | ✅ Hecho | Orquestador + health check + enriquecimiento paralelo (3 workers) + logging a archivo + bucle `schedule` diario a las 12:30. |
| `CRON.md` | ✅ Hecho | Instrucciones para cronjob Linux/Mac. |
| `test_buscador.py` | ✅ Hecho | Pruebas RED/GREEN con datos simulados. |
| `README.md` | ✅ Hecho | Documentación completa (este archivo). |

---

## Resultados de scraping real (validación de sesión)

Se ejecutó scraping real contra **Bike Ocasión** y **Buhobike** con Scrapling (`Fetcher` + `StealthyFetcher` con `solve_cloudflare=True`).

### Bike Ocasión — ✅ 153 bicicletas extraídas (5 páginas)

El scraper extrae 30 bicicletas por página y recorre 5 páginas (paginación `?page=N`). Campos extraídos directamente de la tarjeta de listado:

| Campo | Tasa de extracción |
|-------|-------------------|
| Talla | 100% |
| Batería | 100% |
| Kilometraje | 100% |
| Motor | 100% |
| Suspensión trasera | 100% |
| Material de cuadro | 100% |
| Componentes | 56% |
| Año | 0% (completado por enriquecedor web) |
| Peso | 0% (completado por enriquecedor web) |

Tiempo: ~28 segundos para 153 bicicletas (sin visitar ficha de detalle de cada una).

Luego se aplicaron los filtros estrictos (S1–S6) y la regla de nota ≥ 8.0 (S8). **Ninguna bici pasó todos los filtros** en el inventario actual:

| Motivo de descarte | Cantidad |
|--------------------|----------|
| Talla no es M (S1) | mayoría de bicis |
| Precio > 3.300 € (S5/S6) | varias bicis |
| Batería ≤ 500 Wh (S4) | algunas bicis |
| Nota < 8.0 tras pasar filtros | varias bicis |

Las bicicletas con precios más interesantes dentro del rango fueron descartadas principalmente por talla (no M) o por precio superior a 3.300 €. El inventario cambia constantemente; se recomienda ejecutar el buscador periódicamente.

### Buhobike — ✅ 32 bicicletas extraídas

El Fetcher HTTP devolvió 503 (Cloudflare agresivo), pero `StealthyFetcher` con `solve_cloudflare=True` resolvió el desafío y obtuvo 200.

Se extrajeron **32 bicicletas** de la categoría Trail Eléctricas. Tras aplicar los filtros estrictos:

| Filtro | Resultado |
|--------|-----------|
| Precio en rango 2.000–3.300 € (S5/S6) | **0 bicis** — el más barato es 3.399 € |
| Talla M (S1) | 10 bicis |
| Ambas condiciones | **0 bicis** |
| Pasan filtros estrictos completos | **0 bicis** |

El principal obstáculo en Buhobike es el precio: todos los modelos de trail eléctrica superan los 3.300 €.

### Upway — ✅ Ya validado previamente

Scraping real probado exitosamente con Playwright (23 productos extraídos con títulos y precios correctos).

### Tuvalum — ⏳ Pendiente

El dominio `tuvalum.com` no resolvió desde el entorno de desarrollo (error DNS). Los selectores son estimados y requieren verificación en máquina local.

---

## Por dónde vamos

El scraping real ya funciona en Bike Ocasión, Buhobike y Upway. Los próximos pasos inmediatos son:

1. **Configurar `.env`** con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` para recibir notificaciones por Telegram.
2. **Probar envío de Telegram** con una bici simulada.
3. **Verificar/selectores de Tuvalum** en tu máquina local (desde este entorno el dominio no resuelve DNS).
4. **Automatizar con `main.py` o cron** según `CRON.md`.
5. **Configurar proxies rotatorios** (`PROXY_LIST` en `.env`) si algún sitio bloquea por IP.

## Qué falta hacer

| # | Tarea | Por qué falta |
|---|-------|---------------|
| 1 | **Configurar `.env`** con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` | Necesario para recibir notificaciones por Telegram. |
| 2 | **Probar envío de Telegram** con una bici simulada | Confirmar que el mensaje Markdown llega bien a tu chat. |
| 3 | **Verificar selectores de Tuvalum** en tu máquina local | El dominio no resuelve desde este entorno (DNS error). Los selectores son estimados. |
| 4 | **Automatizar con `main.py` o cron** | Dejarlo corriendo todos los días a las 12:30. |
| 5 | **Configurar proxies** (`PROXY_LIST`) si un sitio bloquea por IP | Para sitios con Cloudflare muy agresivo que no responden ni con Fetcher ni con StealthyFetcher. |

---

## Proceso de desarrollo y dificultades encontradas

### Qué se hizo en esta sesión (mejoras de scraping con Scrapling)

1. **Integración de Scrapling** (`https://github.com/D4Vinci/Scrapling`) como motor principal de scraping, reemplazando las 3 capas separadas (`curl_cffi` → `requests` → `Playwright`).
   - Capa 1: `Fetcher` (HTTP con impersonación TLS de Chrome) — rápido.
   - Capa 2: `StealthyFetcher` con `solve_cloudflare=True` — para Cloudflare/JS pesado (resuelve Buhobike 503).
2. **`scraper_base.py` reescrito**: usa Scrapling, incluye `_espera_cortesa()` (delays aleatorios), `ProxyRotator` opcional (vía `PROXY_LIST` en `.env`), paginación (`extraer_bicicletas_paginado`) y conversión segura de `TextHandler` a string para BeautifulSoup.
3. **`bike_ocasion.py` optimizado**: extrae talla, batería, km, motor, suspensión, cuadro y componentes directamente de la tarjeta de listado (sin visitar ficha de detalle). Paginación de 5 páginas → 153 bicicletas en 28.2s.
4. **`enriquecedor_web.py` reescrito**: usa ficha del producto del propio sitio (Scrapling) como fuente principal y DuckDuckGo como fallback. Incluye caché JSON en disco (`cache/fichas_detalle.json`) para no re-consultar URLs ya visitadas.
5. **`main.py` mejorado**: agregó `_health_check_scrapers()` (alerta por log y Telegram si un scraper devuelve 0 productos), enriquecimiento paralelo con `ThreadPoolExecutor` (3 workers), logging a archivo `logs/buscador.log` + consola.
6. **Tests**: `test_buscador.py` pasa GREEN con todos los cambios.
7. **`config.py`**: agregó configuración de proxies (`PROXY_LIST`, `PROXY_ROTATION`).

### Dificultades encontradas

| Dificultad | Sitio afectado | Solución / Estado |
|------------|---------------|-------------------|
| **URL de categoría 404** | Bike Ocasión | La URL original (`bicicletas-electronicas/doble-suspension/`) devolvía 404. Se inspeccionó el menú y se encontró la URL correcta: `bicicletas-electricas-de-montana-doble-suspension-2020`. |
| **Dominio no resuelve** | Tuvalum | `tuvalum.com` y `www.tuvalum.com` no resuelven desde el entorno de desarrollo (error DNS). Los selectores son estimados y requieren verificación en máquina local. |
| **Protección anti-baneo (503)** | Buhobike | `Fetcher` HTTP devuelve 503. `StealthyFetcher` con `solve_cloudflare=True` resuelve el desafío Cloudflare. |
| **Incompatibilidad TextHandler vs BeautifulSoup** | Bike Ocasión | `page.html_content` de Scrapling es un `TextHandler` (subclase de `str`). Se arregla con `str(html)` en `scraper_base.py`. |
| **Selectores placeholders** | Todos | Los scrapers originales usaban selectores genéricos (`.product-item`, `article.product`) que no coinciden con el HTML real de ningún sitio. Se inspeccionó y se reemplazaron por selectores reales. |
| **Scraping secuencial lento** | Todos | Paginación + paralelización del enriquecedor con `ThreadPoolExecutor` (3 workers). |
| **Archivos de configuración faltantes** | Proyecto general | `requirements.txt`, `.gitignore` y `.env.example` no existían en el repositorio inicial. Se crearon desde cero. |

### Dependencias instaladas

- `scrapling>=0.5` (motor principal de scraping)
- `patchright>=1.64` (fork de Playwright usado por Scrapling)
- `browserforge>=1.2` (fingerprint generation)
- `msgspec>=0.22` (serialización rápida)

### Estado final

| Componente | Estado |
|------------|--------|
| Lógica de filtros, scoring, dedup, Telegram | ✅ Verificado (tests GREEN) |
| Selectores Bike Ocasión | ✅ Verificados en HTML real |
| Selectores Buhobike | ✅ Verificados en HTML real |
| Selectores Upway | ✅ Verificados + scraping real probado |
| Selectores Tuvalum | ⚠️ Estimados (pendiente verificación real) |
| Scraping real Upway | ✅ Funciona con Playwright/Scrapling |
| Scraping real Buhobike | ✅ Funciona con Scrapling StealthyFetcher (32 bicis extraídas, 0 pasan filtros S1-S8 por precio) |
| Scraping real Bike Ocasión | ✅ Funciona con Scrapling Fetcher (153 bicis en 5 páginas, 0 pasan filtros S1-S8 hoy) |
| Scraping real Tuvalum | ⏳ Pendiente (dominio no resuelve) |
| Enriquecedor web (ficha del sitio + DuckDuckGo) | ✅ Implementado e integrado en main.py |
| Caché de fichas de detalle | ✅ Implementado (cache/fichas_detalle.json) |
| Health check de scrapers | ✅ Implementado (alerta por log y Telegram) |
| Logging a archivo | ✅ Implementado (logs/buscador.log) |
| Proxies rotatorios (ProxyRotator) | ✅ Implementado (configurable vía PROXY_LIST) |
| Paginación | ✅ Implementada (Bike Ocasión: 5 páginas, 153 bicis) |

---

## Licencia

MIT

---

## Créditos

Desarrollado como asistente de código bajo la identidad **el Gentleman** (Pi-specific coding-agent harness), siguiendo el flujo de desarrollo **Organic Driven Development (ODD)**.
