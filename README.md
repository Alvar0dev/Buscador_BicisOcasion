# 🚵‍♂️ Buscador de e-MTB de Ocasión

Script modular en Python para rastrear automáticamente tiendas profesionales de reacondicionado de bicicletas y encontrar ofertas de bicicletas eléctricas de montaña (e-MTB) doble suspensión que cumplan con filtros estrictos de talla, modalidad, peso, batería y precio.

Cuando encuentra bicicletas aptas tras superar los filtros estrictos, las audita con un **Perito Mecánico Escéptico y Estricto (v2)** y envía por Telegram **1 mejor bicicleta por cada portal con stock** (con rotación ping-pong `#1 -> #2 -> #1` si la mejor opción de una página no cambia entre corridas consecutivas), evitando alertas repetitivas salvo bajadas de precio o verificación de liderazgo.

## Tabla de contenidos

- [¿Qué hace este proyecto?](#qué-hace-este-proyecto)
- [Requisitos estrictos de filtrado](#requisitos-estrictos-de-filtrado)
- [Algoritmo de Nota de Oportunidad (Perito Mecánico Escéptico v2)](#algoritmo-de-nota-de-oportunidad-perito-mecánico-escéptico-v2)
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
- [Próximos pasos y Roadmap](#próximos-pasos-y-roadmap)
- [Por qué se ha construido así (Arquitectura e Ingeniería de Decisiones)](#por-qué-se-ha-construido-así-arquitectura-e-ingeniería-de-decisiones)
- [Proceso de desarrollo y dificultades encontradas](#proceso-de-desarrollo-y-dificultades-encontradas)
- [Estado actual y TODOs para mañana (Próxima Sesión)](#estado-actual-y-todos-para-mañana-próxima-sesión)
- [Licencia](#licencia)

---

## ¿Qué hace este proyecto?

Este script rastrea diariamente las secciones de e-MTB doble suspensión de cuatro tiendas profesionales de bicicletas con garantía oficial y los anuncios geolocalizados de Wallapop (radio de 50 km desde Fuenlabrada, Madrid):

- **Bike Ocasión** (bike-ocasion.com)
- **Buhobike** (buhobike.com)
- **Upway** (upway.es)
- **Mammoth Bikes** (mammothbikes.com)
- **Wallapop** (es.wallapop.com — radio 50 km desde Fuenlabrada)

Para cada bicicleta encontrada aplica una serie de filtros estrictos y, si pasa, le asigna una **Nota de Oportunidad del 0 al 10**. Solo las bicicletas con nota **≥ 8.0** se guardan en una base de datos local SQLite y se envían por Telegram para evitar alertas duplicadas (salvo que bajen de precio).

La ejecución está programada para correr todos los días a las **12:00 de la mañana**.

---

## Requisitos estrictos de filtrado

| ID | Requisito | Detalle |
|----|-----------|---------|
| **S0** | Disponibilidad | Exclusivamente unidades **en stock** (se descartan preventivamente unidades marcadas como *Reservada*, *Agotada*, *Vendida* o *Sin stock*). |
| **S1** | Talla | Exclusivamente **Talla M** (aprox. 165 cm - 179 cm). |
| **S2** | Modalidad | **XC / Cross Country / Downcountry / Light e-MTB**. |
| **S3** | Peso | Máximo **19 kg** (se priorizan cuadros de carbono y motores ligeros; se descartan modelos > **21 kg**). |
| **S4** | Batería | Capacidad nominal estrictamente **> 500 Wh** (ej. 540 Wh o interna + Range Extender incluido). |
| **S5** | Precio principal | Rango de **2.000 € a 3.000 €**. |
| **S6** | Precio excepcional | Si es una "oportunidad excepcional" (bici muy nueva, componentes tope de gama), el precio puede llegar hasta **3.300 €**. |

---

## Algoritmo de Nota de Oportunidad (Perito Mecánico Escéptico v2)

El sistema opera bajo las reglas deterministas de un **Perito Mecánico Escéptico y Estricto (`perito_v5`)**: parte de **BASE = 10.0 sin bonos positivos**, prohíbe inventar componentes, aplica física realista anti-optimismo de peso (`Full Power + >= 625 Wh` o sin batería confirmada `>= 22.5 kg` salvo excepciones ligeras explícitas), corrige erratas de motor (`BH iLynx Race/Trail` sin `+` = `BH 2EXMAG` cerrado; `BH iLynx+` = `Shimano EP801` abierto; `Orbea Rise 2021-2022` = `EP8-RS`; `2025+` = `EP801-RS Gen2`; `Bosch` = solo taller oficial sin SoH en app de usuario) y limita la nota final mediante **5 Líneas Rojas**:

| Línea Roja Eliminatoria | Tope de Nota |
|-------------------------|--------------|
| Talla distinta de `M` (`S`, `L`, `XL`, etc.) | **0.0 / 10** (`DESCARTADA`) |
| Batería interna/total `< 500 Wh` | **4.0 / 10** (`DESCARTADA`) |
| Peso real o estimado `> 21.0 kg` | **4.0 / 10** (`DESCARTADA`) |
| Kilometraje `> 6.000 km` | **4.5 / 10** (`DESCARTADA`) |
| Anuncio genérico sin marca ni modelo identificable | **4.5 / 10** (`DESCARTADA`) |

### 1. Kilometraje y Desgaste (incluye contradicciones)
* **0 a 1.000 km** (sin contradicciones): **-0.0 pts**
* **1.001 a 2.000 km**: **-1.0 pt**
* **2.001 a 4.000 km**: **-2.5 pts**
* **4.001 a 6.000 km**: **-3.5 pts**
* **> 6.000 km**: **-4.5 pts** (activa Línea Roja `4.5`)
* **No especificado o contradicción** (`"NUEVA"` / `"ESTRENAR"` + `km > 50`): **-2.0 pts** (o mantiene la resta mayor de tramo si supera `2.000 km` mediante `min(delta_km, -2.0)`).

### 2. Peso Real Estimado (sin bonos y anti-optimismo)
* **<= 19.0 kg**: **-0.0 pts**
* **19.1 a 20.0 kg**: **-0.5 pts**
* **20.1 a 21.0 kg**: **-1.5 pts**
* **> 21.0 kg**: **-6.0 pts** (activa Línea Roja `4.0`)

### 3. Motor, Diagnosis y Batería (SoH / Ciclos)
* **Shimano EP8 / EP801 / EP6** (incluida `BH iLynx+`) o **Specialized**: **-0.0 pts** (auditables vía app propia o PCE02).
* **Bosch Performance CX / SX** sin informe oficial completo de taller: **-0.5 pts** (Bosch no expone ciclos ni SoH en la app de usuario).
* **Motor propietario cerrado** (`BH 2EXMAG` sin `+`, `Brose` antiguo, otros): **-0.5 pts** (`<= 2.000 km`) o **-1.0 pt** (`> 2.000 km` / desconocido).
* **Penalización extra sin SoH ni ciclos**: **-0.5 pts** adicionales si no aporta SoH/ciclos y tiene `> 1.500 km` o kilometraje desconocido.

### 4. Garantía y Canal de Venta
* **Tienda profesional en España** (`>= 1 año` garantía legal): **-0.0 pts**
* **Tienda extranjera / sin reseñas verificadas**: **-1.0 pt**
* **Particular con factura vigente** (`< 2 años`, detectada vía `tiene_factura`): **-1.0 pt**
* **Particular sin garantía comercial ni mención de factura**: **-1.5 pts**

### 5. Precio y Componentes Declarados
* **2.000 € - 3.000 €** con transmisión 12v (SLX/XT/GX) y suspensiones gama media-alta: **-0.0 pts**
* **Precio 3.001 € - 3.150 €** (margen negociable): **-0.5 pts** | **> 3.150 €**: **-2.0 pts**
* **Montaje básico/obsoleto** (`10v/11v`, frenos `MT200/MT401`, horquilla básica) costando `> 2.400 €`: **-0.5 a -1.0 pt**
* **Componentes principales no detallados** en el anuncio (`NO ESPECIFICADO`): **-1.5 pts**

---

## Integración con Telegram

El script usa la API de Telegram vía `requests` y envía un mensaje en **Markdown** con:

- Título de la bicicleta y precio.
- **Nota de Oportunidad destacada** (ej. 🔥 8.5/10).
- Kilómetros, capacidad de batería y material del cuadro.
- **Desglose breve** de por qué sacó esa nota.
- **Enlace directo de compra**.
- **Segmentación sonora (TODO 3)**: Las ofertas normales y el Heartbeat se entregan en silencio (`disable_notification=True`). Únicamente los verdaderos **Mega Chollos** (Nota $\ge$ 9.0 y dto $\ge$ 50% vs PVP nuevo) disparan notificación sonora/prioritaria con timbre (`disable_notification=False`), configurable mediante `TELEGRAM_SILENCIAR_OFERTAS_NORMALES=true`.
- **Canal exclusivo Black Friday (`Black_Bike_Beast`)**: Segundo bot independiente (`TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` y `TELEGRAM_CHAT_ID_BLACK_FRIDAY`, con fallback a `TELEGRAM_CHAT_ID`) que vigila bicis **nuevas o de exposición (`<= 50 km`, Talla M, `< 21.0 kg`, `>= 500 Wh`, doble suspensión) hasta `3.500 €`** con descuento real **`>= 35%` sobre PVP** (`nota_bf >= 7.5/10`), sin alterar el techo diario de `3.300 €` ni la rotación del canal principal.

Requiere configurar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el archivo `.env` (y opcionalmente `TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` / `TELEGRAM_CHAT_ID_BLACK_FRIDAY` para el canal Black Friday).

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
- buhobike.com
- upway.es
- mammothbikes.com

**Bajo ningún concepto se incluye código para rastrear plataformas de trato entre particulares** como Wallapop, Milanuncios o foros, ya que no ofrecen garantía mecánica certificada.

---

## Arquitectura modular

El proyecto está separado en módulos con responsabilidad única:

| Archivo | Responsabilidad |
|---------|-----------------|
| `config.py` | Configuración central: URLs objetivo optimizadas, filtros estrictos, credenciales Telegram/Gemini, user-agents rotatorios, proxies (opcional), flags operativos (`TELEGRAM_HEARTBEAT`), horario de ejecución. |
| `models.py` | Dataclass `Bicicleta` con todos los campos necesarios para scoring, telemetría de batería (`bateria_salud_pct`, `bateria_ciclos`), `pvp_original` y notificación. |
| `db.py` | Base de datos SQLite: registro de bicicletas ya enviadas, deduplicación por ID y tabla dedicada `bicis_black_friday_enviadas` para el segundo bot, detección de bajadas de precio, historial de catálogo (`historial_catalogo`), permanencia en stock y métricas agregadas con PVP original. |
| `evaluator.py` | Filtros estrictos (S1-S6), algoritmo de Nota de Oportunidad, ordenamiento por prioridad de modalidad (`prioridad_modalidad`), más pre-filtro y rúbrica específica Black Friday (`evaluar_oportunidad_black_friday`) para nuevas/exposición `<= 3.500 €`. |
| `gemini_classifier.py` | Motor Perito Mecánico Senior (`auditar_perito_mecanico`), catálogo técnico de e-MTB, desambiguación de motores BH (BH 2EXMAG vs Shimano EP801) y clasificador híbrido con Gemini Flash + caché thread-safe. |
| `notifier.py` | Notificador unificado de Telegram vía `requests` (`_enviar_telegram`), ficha diaria Markdown, alertas exclusivas de Black Friday para el segundo bot (`enviar_black_friday`) y Heartbeat operativo diario (`enviar_heartbeat`). |
| `scraper_base.py` | Clase base con **motor Scrapling**: `Fetcher` (HTTP con impersonación TLS) → `StealthyFetcher` (navegador stealth con `solve_cloudflare=True`), con `usar_stealth_directo` y salto inmediato ante bloqueos HTTP 403/503 de Cloudflare. |
| `scrapers/bike_ocasion.py` | Adaptador específico para Bike Ocasión. Extrae título limpio (`h3.s_title_block a`), talla, batería, km, marca del motor (`Km / <Marca>`), PVP original y doble suspensión directamente de la tarjeta del listado. Paginación de hasta 6 páginas (180+ bicis). |
| `scrapers/buhobike.py` | Adaptador específico para Buhobike con modo stealth directo (`usar_stealth_directo=True`), rastreo combinado de `/3230-electricas-trail-dobles?order=product.price.asc` y `/9448-segunda-mano-montana-electricas`, y extracción en tarjeta de título completo (`img.thumbnail-img[alt]`), talla (`#/...-talla-m`), año, km desde SKU (`KM5000`) y PVP original. |
| `scrapers/upway.py` | Adaptador específico para Upway sobre `/collections/doble-suspension`. Extrae año, kilometraje (`\u202fkm` y `< 5 km`), talla (desde el rango de estatura `1mXX-1mYY`), PVP original nuevo ('6.000 € nuevo') y doble suspensión directamente de la tarjeta en `< 1s`. |
| `scrapers/mammoth.py` | Adaptador específico para Mammoth Bikes sobre `/bicicletas-electricas-mtb-dobles-rally-xc/c-3104` y `/bicicletas-electricas-mtb-trail-all-mountain-dobles/c-2139`. Extrae precio, tallas en stock (`M`), modalidad XC, año, PVP original tachado (`.is__old`), telemetría de bici nueva (km=0, SoH=100%, 0 ciclos) y filtro anti-rígidas directamente de `div.card-content` en `~2.5s`. |
| `scrapers/enriquecedor_web.py` | Enriquecedor web paralelo con caché JSON en disco (`cache/fichas_detalle.json`), extracción de pares `<dt>/<dd>`, telemetría de batería (SoH % y ciclos), limpieza de DOM y regex con bordes de palabra (`\b`) y filtrado de pesos con embalaje. |
| `main.py` | Orquestador: scrape de los sitios → **health check** → pre-filtro → **enriquecimiento paralelo** → auditoría Perito Mecánico Senior → ordenamiento por salud mecánica (`nota >= 6.0` y `km <= 4.000`), Línea Roja y prioridad de modalidad (`XC > Light e-MTB > Trail`) → SQLite → Telegram (`--once`, `--forzar`, `--stats`, `--heartbeat`). |
| `test_buscador.py` | Suite de pruebas unitarias RED/GREEN con datos simulados para validar filtros, Perito Mecánico Senior, scrapers de tarjetas, prioridad de modalidades y dedup. |
| `CRON.md` | Instrucciones para ejecutar mediante cronjob en Linux/Mac o Programador de tareas de Windows. |
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

1. **Selectores CSS inspeccionados.** Los selectores de Bike Ocasión, Buhobike y Upway ya fueron inspeccionados en el HTML real de cada web (vía ego-browser).

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
- [ ] Automatizar con `main.py` o cron según `CRON.md`.
- [x] Configurar proxies rotatorios (`PROXY_LIST` en `.env`) con soporte nativo de rotación cíclica y aleatoria en Scrapling (`scraper_base.py`).

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
| `scrapers/` (3 sitios) | ✅ Hecho | Bike Ocasión, Buhobike y Upway con selectores reales verificados y scraping real probado. |
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

### Resumen de sitios activos

| Sitio | Estado | Bicis extraídas |
|-------|--------|-----------------|
| Bike Ocasión | ✅ Funciona con Scrapling Fetcher | 182 (6 páginas) |
| Buhobike | ✅ Funciona con Scrapling StealthyFetcher (`usar_stealth_directo=True`) | 48 (dobles + segunda mano) |
| Upway | ✅ Funciona con Scrapling Fetcher (en tarjeta ~0.8s) | 23 (/collections/doble-suspension) |
| Mammoth Bikes | ✅ Funciona con Scrapling Fetcher (en tarjeta ~2.6s) | 65 (Rally/XC dobles + Trail dobles) |

---

## Estado operativo actual

El sistema se encuentra en **producción activa y 100% automatizado**:
- **Scrapers en producción**: Bike Ocasión (6 páginas, 180+ bicis), Buhobike (dobles ordenadas por precio + segunda mano), Upway (`/collections/doble-suspension` en 0.8s) y Mammoth Bikes (`c-3104` Rally/XC + `c-2139` Trail dobles en ~2.6s).
- **Ordenamiento calibrado (`clave_orden_estrictas`)**: Prioriza primero la salud mecánica (`nota >= 6.0` y `km <= 4.000`), después ausencia de Línea Roja, luego modalidad (`XC / Downcountry` > `Light e-MTB` > `Trail`), mayor nota pericial y menor peso.
- **Extracción de odómetro híbrida (Regex + Visión IA)**: Filtro estricto de contexto negativo en texto (bloquea menciones de cadena, cera o garantía) + inspección visual de la galería con Gemini Vision para cuentakilómetros fotografiados.
- **Notificaciones automáticas**: Integradas con Telegram en formato Markdown, informando la Nota Pericial en 5 ejes, desglose aritmético y alertas destacadas de bajada de precio (`📉 ¡BAJADA DE PRECIO DETECTADA!`).
- **Automatización**: Tarea programada en Windows Task Scheduler (`BuscadorBiciOcasion`) a las 12:00 de cada día (`main.py --once` con `WakeToRun: True` y `StartWhenAvailable: True`).

## Próximos pasos y Roadmap

| # | Tarea | Estado | Detalle |
|---|-------|--------|---------|
| 1 | **Calibración continua de scoring y ordenamiento** | ✅ Completado | Priorización de salud mecánica (`nota >= 6.0`, `km <= 4.000`) antes que modalidad XC para evitar que unidades muy castigadas (> 4.000 km) encabecen el Top 3. |
| 2 | **Alertas de bajada de precio con historial visual** | ✅ Completado | Notificación explícita con cálculo de ahorro en euros cuando una bicicleta previamente registrada baja de precio. |
| 3 | **Nuevos portales profesionales certificados** | ✅ Completado | Integrado `MammothScraper` (`mammothbikes.com`, categorías Rally/XC y Trail doble suspensión con 3 años de garantía oficial) tras descartar definitivamente Tuvalum. |
| 4 | **Detección multimodal de odómetros y filtro anti-falsos positivos** | ✅ Completado | Extracción con Gemini Vision de displays en fotos de segunda mano y bloqueo de texto de lubricación/cadena. |
| 5 | **Despertar automático en Task Scheduler (`WakeToRun`)** | ✅ Completado | Configurado `WakeToRun: True`, `StartWhenAvailable: True` y ejecución en batería en la tarea `BuscadorBiciOcasion` de Windows Task Scheduler. |
| 6 | **Detección de Range Extender en descripción** | ✅ Completado | Detección de inclusión real (+180 Wh en BH / +252 Wh en Orbea / +160 Wh en TQ y Specialized / +250 Wh en Bosch PowerMore), rescate de filtro estricto S4 (Rise 360 Wh + 252 Wh = 612 Wh > 500 Wh), bonificación de +0.5 pts en calidad-precio, reflejo en desglose pericial y mensaje de Telegram. |
| 7 | **Telemetría real de Salud de Batería (SoH % y ciclos)** | ✅ Completado | Extracción automática de `bateria_salud_pct` (`Estado de salud: 90 %`, `% batería: 95%`, `conserva el 89 % de su capacidad original`) y `bateria_ciclos` (`Número de ciclos de carga: 164`), preservando los Wh nominales en `bateria_wh` y ponderando el SoH real en el Perito Mecánico Senior y en Telegram (`[SoH: XX% | YY ciclos]`). |
| 8 | **Filtro preventivo anti-Reservadas/Agotadas y Scraping Multi-Portal Paralelo** | ✅ Completado | Descarte inmediato de unidades reservadas/agotadas en los 4 scrapers (`es_tarjeta_no_disponible`), en la ficha de detalle (`_extraer_disponibilidad_ficha`) y en el filtro `S0`, más ejecución en paralelo de los 4 portales (`ThreadPoolExecutor`) reduciendo el tiempo de corrida a ~57s. |
| 9 | **Historial de evolución de precios y "Tiempo en Stock" (`historial_catalogo`)** | ✅ Completado | Registro persistente en SQLite de todas las candidatas pre-filtradas con cálculo de días en catálogo, detección de rebajas acumuladas y ahorro total, visible en Telegram (`⏳ X días en catálogo | 🏷️ Y rebaja(s)`). |
| 10 | **Clasificación objetiva de modalidad por recorrido de suspensión (mm)** | ✅ Completado | Extracción en `enriquecedor_web.py` de milímetros físicos de horquilla/amortiguador (`_extraer_recorrido`), ponderación directa en `prioridad_modalidad` (`≤130 mm` XC > `140 mm` Light Trail > `150-160 mm` All-Mountain) y descarte por S2bis de modelos `> 170 mm` (Enduro/DH). |
| 11 | **Modo radar de mercado CLI (`python main.py --stats`) y exportación Markdown (`docs/radar_mercado.md`)** | ✅ Completado | Comando de consola (`--stats` o `--radar`) y generación automática de `docs/radar_mercado.md` en cada corrida con unidades por tienda, precios medios/mínimos de modelos estrella (*Orbea Rise*, *BH iLynx*), unidades en vigilancia (2.900–3.500 €) y rebajas activas. |
| 12 | **Extracción multimodal en lote de odómetros en imágenes (`gemini-3.5-flash-lite`) y tabla técnica Buhobike** | ✅ Completado | Cuando `km` no aparece en string ni int en los datos/ficha, inspecciona hasta 6 fotos de galería en una única llamada multimodal a Gemini Vision (`4238 km` detectados en foto #3 de Orbea Rise H10) y extrae peso de báscula (`19,57Kg`) de `table.caracteristicas-tecnicas-2-tablas` y `#product-details`. |
| 13 | **Alertas proactivas de Entrada desde Zona de Vigilancia** | ✅ Completado | Seguimiento activo de bicicletas hasta 3.500 € en `historial_catalogo` y disparo de cabecera prioritaria `🚨 ¡ENTRADA DESDE ZONA DE VIGILANCIA! BAJADA DE PRECIO DETECTADA` cuando bajan a `<= 3.000 €` o acumulan `>= 200 €` de descuento. |
| 14 | **Soporte robusto de Proxies Rotatorios (`PROXY_LIST` y `PROXY_ROTATION`)** | ✅ Completado | Integración de `ProxyRotator` en `scraper_base.py` y `enriquecedor_web.py` con soporte para rotación cíclica y aleatoria en `Fetcher` y `StealthyFetcher` ante bloqueos de IP en Cloudflare. |

---

## Por qué se ha construido así (Arquitectura e Ingeniería de Decisiones)

El sistema no es un simple scraper de precios: está diseñado como un **embudo pericial determinista en dos fases** que combina velocidad de red, evasión selectiva anti-bot y auditoría mecánica estricta. Cada decisión arquitectónica responde a un problema real encontrado en producción:

### 1. Embudo en 2 fases: Extracción densa en tarjeta → Enriquecimiento paralelo selectivo
* **Por qué**: Rastrear las ~320 bicicletas de los 4 portales entrando una por una a su ficha de producto requeriría > 320 peticiones HTTP/Stealth por corrida (> 12 minutos) y provocaría bloqueos por *rate-limiting* en Cloudflare.
* **Cómo se construyó**:
  1. **Fase 1 (Listado en paralelo)**: Los 4 scrapers (`bike_ocasion`, `buhobike`, `upway`, `mammoth`) corren en paralelo mediante `ThreadPoolExecutor(max_workers=4)`. Cada adaptador extrae directamente del HTML de la tarjeta de listado la mayor cantidad de metadatos posible (talla, precio, doble suspensión, disponibilidad, y en Bike Ocasión/Upway también batería, km y motor).
  2. **Pre-filtro en memoria (`_pasa_prefiltro`)**: Descarta en milisegundos el ~92% del catálogo (tallas S/L/XL, rígidas, precios > 3.300 €, agotadas/reservadas).
  3. **Fase 2 (`EnriquecedorWeb` con 5 workers y caché en disco)**: Solo las ~10-25 candidatas viables visitan su ficha individual de detalle (y DuckDuckGo como respaldo de catálogo) para completar peso exacto, odómetro, SoH % de batería y componentes. Las fichas ya visitadas se persisten en `cache/fichas_detalle.json`.

### 2. Motor dual anti-baneo (`Fetcher` TLS vs `StealthyFetcher` Cloudflare)
* **Por qué**: Levantar un navegador headless Chromium para todas las tiendas consume mucha RAM y multiplica por 10x la latencia, pero usar `requests` estándar falla con HTTP 403/503 en tiendas protegidas por Cloudflare.
* **Cómo se construyó**: `BaseScraper` utiliza **Scrapling** en dos niveles:
  * **Nivel 1 (`Fetcher`)**: Peticiones HTTP ultrarrápidas con *TLS fingerprinting* de Chrome real. Extrae Upway en `0.8s`, Mammoth en `2.6s` y 6 páginas de Bike Ocasión en `~18s`.
  * **Nivel 2 (`StealthyFetcher` con `solve_cloudflare=True`)**: Se activa automáticamente ante un HTTP 403/503 o de forma directa (`usar_stealth_directo=True` en Buhobike) para resolver el desafío JavaScript de Cloudflare sin intervención humana.

### 3. Regla Maestra del Perito Mecánico Senior (Deducción irreversible vs Media ponderada)
* **Por qué**: En un sistema de puntuación por suma o media ponderada tradicional, una bicicleta con cuadro de carbono, cambio Shimano XT y suspensión Fox Kashima pero con **6.200 km** de desgaste o **22.5 kg** de peso seguiría obteniendo ~7.5/10, engañando al comprador con una falsa ganga que requiere 900 € en taller.
* **Cómo se construyó**:
  * Toda bicicleta parte de **10.0 puntos** y solo puede **perder** puntos por desgaste mecánico (salvo bonificaciones acotadas por peso pluma `< 19 kg`, transmisión electrónica/XT, Range Extender incluido o batería con `SoH >= 92%`).
  * **Líneas Rojas irreversibles**: Si `km > 6.000` (nota capada a máx `4.5/10`) o `peso > 21.0 kg` (nota capada a máx `4.0/10`), ningún componente tope de gama puede rescatarla.
  * **Escalón de salud mecánica en el ranking (`clave_orden_estrictas`)**: Antes de ordenar por modalidad preferida (`XC / Downcountry` > `Light e-MTB` > `Trail`), el orquestador exige un escalón primario de salud (`nota >= 6.0` y `km <= 4.000`). Así, una XC muy castigada jamás supera en el Top 3 a una Light e-MTB mecánicamente impecable.

### 4. Telemetría de Batería en 3 dimensiones: Capacidad Nominal, Range Extender y SoH %
* **Por qué**: El análisis de las fichas reales reveló dos trampas opuestas en los portales de segunda mano:
  1. **Trampa de descarte por batería interna pequeña en Light e-MTB**: Modelos ultraligeros de 18 kg (ej. *Orbea Rise 360 Wh* o *BH iLynx*) se descartaban en el filtro `S4 (<= 500 Wh)` aunque incluyeran en el precio el **Range Extender oficial** (+252 Wh / +180 Wh = 540–612 Wh reales).
  2. **Trampa de descarte por capacidad efectiva degradada en Upway**: Upway publica frases de laboratorio como *"conserva el 89 % de su capacidad original de 750 Wh, es decir, 670 Wh"*. En una batería de 540 Wh al 90% de salud (~486 Wh efectivos), tomar el valor efectivo hacía que la bici cayera falsamente en el filtro `S4 (<= 500 Wh)`.
* **Cómo se construyó**:
  * `_extraer_bateria` prioriza siempre la `"capacidad original de XXX Wh"` para preservar la capacidad nominal de diseño en `bateria_wh`.
  * `_detectar_range_extender` analiza el contexto semántico: suma los Wh externos (`+252 Wh`, `+180 Wh`, `+160 Wh`, `+250 Wh`) **solo** cuando hay inclusión explícita (`+`, `incluye`, `con`, `regalo`) e ignora menciones comerciales de compatibilidad (`compatible con`, `opcional`, `no incluido`).
  * `_extraer_salud_bateria` captura por separado `bateria_salud_pct` (`% SoH`) y `bateria_ciclos` para premiar o castigar la degradación química real de las celdas en el Perito Mecánico Senior (`>= 92%: +0.5`, `80-84%: -1.0`, `< 80%: -2.5`).

### 5. Auditoría de Odómetro en Doble Capa: Bloqueo Léxico + Visión Multimodal (Gemini Flash)
* **Por qué**: Caso real detectado en producción con la *Orbea Rise H10 T-M* en Buhobike: la tienda no puso los kilómetros ni en el título, ni en el SKU, ni en la tabla técnica; solo subió una **foto del display Shimano marcando 4.237 km**. A la vez, el texto comercial del anuncio decía *"permite hacerle unos 700 km sin necesidad de engrasar la cadena con cera al agua"*, provocando que un regex numérico ingenuo le asignara `700 km` y nota `10/10`.
* **Cómo se construyó**:
  1. **Capa 1 (Filtro de contexto negativo en `_extraer_km`)**: Se analiza una ventana de ±70 caracteres alrededor de cada mención de `km` y se descarta si aparece vocabulario de taller/mantenimiento (`cadena`, `cera`, `engrasar`, `lubricar`, `autonomía`, `garantía`, `revisión`).
  2. **Capa 2 (Inspección visual con `_extraer_km_de_imagenes`)**: Cuando una bici usada no declara su odómetro en texto, se descargan hasta 6 imágenes de la galería del producto y se envían en una sola llamada multimodal a **Gemini 2.5 Flash Vision** para leer pantallas de Bosch Kiox/Purion, Shimano Steps, Specialized MasterMind o Garmin. Si sigue sin existir dato confirmado en una bici usada, el Perito aplica `-2.0 pts` preventivos por incertidumbre.

### 6. Filtro Transversal Anti-Reservadas / Agotadas (`S0`)
* **Por qué**: Las tiendas de ocasión mantienen visibles durante semanas las bicicletas ya **Reservadas** o **Vendidas** para captar tráfico orgánico de Google. Sin un filtro dedicado, esas bicis consumían llamadas de enriquecimiento e IA y ocupaban huecos en el Top 3 de Telegram.
* **Cómo se construyó**: `BaseScraper.es_tarjeta_no_disponible` inspecciona clases CSS (`.product-unavailable`, `.out-of-stock`, `.reserved`, `.sold-out`) y etiquetas cortas en los 4 scrapers antes siquiera de instanciar la `Bicicleta`. Luego, `_extraer_disponibilidad_ficha` verifica la ficha de producto completa ignorando frases trampa como *"¿Quieres reservarla?"* o *"Reserva tu cita"*.

### 7. Historial Dinámico de Catálogo y Detección de Inmovilización (`historial_catalogo`)
* **Por qué**: Si solo registramos en SQLite las bicicletas que se envían por Telegram (el Top 3 del día), somos ciegos ante la dinámica global de precios: no sabemos cuántos días lleva una unidad sin venderse en la tienda (métrica clave para negociar o detectar sobreprecio) ni podemos avisar cuando una bici de 3.350 € baja a 2.890 € si antes nunca entró en el Top 3.
* **Cómo se construyó**:
  * Se implementó la tabla `historial_catalogo` en `db.py`.
  * Toda bicicleta que pasa el pre-filtro de listado se inserta o actualiza automáticamente registrando `fecha_primera_vez`, `fecha_ultima_vez`, `precio_actual`, `precio_inicial`, `precio_minimo`, `dias_en_stock` y `rebajas_detectadas`.
  * En cada notificación por Telegram, el mensaje incorpora la línea de trazabilidad: `📊 Seguimiento: ⏳ X días en catálogo | 🏷️ Y rebaja(s) (Ahorro: -Z €)`.

### 8. Clasificación Determinista por Recorrido Físico de Suspensión en Milímetros
* **Por qué**: Las tiendas de reacondicionado usan nomenclaturas comerciales inconsistentes en sus títulos (ej. llamar "XC" a una bici de 150 mm o "All Mountain" a una Light e-MTB de 140 mm). Depender exclusivamente de texto o nombres comerciales provocaba que bicis con geometrías pesadas compitieran indebidamente con verdaderas e-MTB de Cross Country / Downcountry.
* **Cómo se construyó**:
  * `_extraer_recorrido` en `enriquecedor_web.py` extrae los milímetros reales de suspensión (`100-180 mm`) analizando tablas `<dt>/<dd>` y menciones directas de horquillas/amortiguadores (`Fox 34 130mm`, `RockShox SID 120 mm`, `Pike 140 mm`).
  * `prioridad_modalidad` en `evaluator.py` supedita el ranking a la cota física: **`≤ 130 mm` -> Nivel 3 (XC / Downcountry)**, **`131–145 mm` -> Nivel 2 (Light Trail / Downcountry largo)**, **`146–165 mm` -> Nivel 1 (Trail / All-Mountain)** y `> 165 mm` -> Nivel 0 (Enduro).
  * Filtro `S2bis`: Descarte automático e inapelable de unidades con recorrido `> 170 mm` (bicicletas de Enduro severo o Freeride incompatibles con el pliego).

### 9. Radiografía de Mercado en CLI (`python main.py --stats`) y Exportación Markdown
* **Por qué**: El usuario y el desarrollador necesitan ver en cualquier momento qué está pasando en el mercado (precios medios de Orbea Rise o BH iLynx, unidades estancadas, oportunidades en zona de vigilancia) sin depender exclusivamente del push diario de las 12:00 ni consultar tablas SQL a mano.
* **Cómo se construyó**: Se implementó `mostrar_radar_mercado()` activable mediante el flag `--stats` (o `--radar`) y la función `exportar_radar_mercado_md()`, que genera automáticamente `docs/radar_mercado.md` en cada corrida resumiendo cuotas de mercado por tienda, modelos clave, alertas de vigilancia (2.900–3.500 €) y rebajas acumuladas.

### 10. Resiliencia de Red y Rotación de Proxies (`ProxyRotator` en Scrapling 0.5)
* **Por qué**: En tiendas con Cloudflare agresivo (Buhobike y Bike Ocasión), realizar scraping frecuente o enriquecer docenas de fichas de detalle desde una misma IP residencial puede provocar bloqueos preventivos por reputación de IP (HTTP 403/503 o CAPTCHAs interactivos). Aunque `StealthyFetcher` resuelve el handshake y JS de Cloudflare, una IP penalizada en origen bloquea cualquier capa de fetch.
* **Cómo se construyó**:
  * Se implementó `crear_proxy_rotator()` en `scraper_base.py`, integrando el `ProxyRotator` nativo de Scrapling con soporte para rotación secuencial cíclica (`cyclic`) y rotación aleatoria (`random`).
  * El rotador se inyecta de forma transparente tanto en peticiones HTTP rápidas (`FetcherSession` y `Fetcher.get`) como en el navegador stealth (`StealthyFetcher.fetch`).
  * Se extendió a `scrapers/enriquecedor_web.py` para que la apertura paralela de fichas de detalle y la descarga binaria de fotos de odómetro también roten proxies si `PROXY_LIST` está configurada en `.env`.

### 11. Odómetros en Lote Multimodal vs Timeouts de Inferencia Individual
* **Por qué**: Al inspeccionar imágenes de galería de producto para leer displays de cuentakilómetros, las llamadas individuales foto por foto con `gemini-flash-latest` (que mapea internamente a Gemini 3.8 Flash con thinking activado) tardaban > 15s por petición y provocaban `ReadTimeout`.
* **Cómo se construyó**: Se agrupan hasta 6 fotos de la galería en un único payload multimodal enviado a `gemini-3.5-flash-lite` (con fallback a `gemini-3.5-flash`), resolviendo toda la galería en 3–5 segundos con 100% de precisión en la extracción del odómetro (ej. `4.238 km` leídos en el display Shimano de Buhobike) y cacheando el resultado con invalidación reactiva si cambia el dato.

### 12. Aislamiento de Peso de Báscula vs Peso con Embalaje en Buhobike
* **Por qué**: En Buhobike, el bloque de descripción y ficha técnica declara `Peso estimado del producto + embalaje: 22,000 Kg` (caja de transporte y protecciones), mientras que el peso neto de la bicicleta (`19,57 Kg`) se encuentra en una tabla estructurada interna. Un extractor genérico tomaba los 22 kg activando el filtro `S3` (> 21 kg) y descartando bicicletas ultraligeras aptas.
* **Cómo se construyó**: Se implementó el parseo estructurado de `table.caracteristicas-tecnicas-2-tablas` (`<tr><th>/<td>`) y del atributo JSON `#product-details[data-product]`, aislando el peso neto de báscula antes de la descomposición del DOM y descartando cualquier valor asociado al texto contextual de `embalaje`.

### 13. Detección y Alerta de "Mega Chollos" (>50% vs PVP) Condicionada a Excelencia Mecánica (Nota ≥ 9.0)
* **Por qué**: Una e-MTB puede tener un 55% de descuento sobre su PVP nuevo, pero si acumula 5.000 km, holguras de basculante o una batería degradada (nota 3.5 o 5.5/10), calificarla de "Mega Chollo" genera falso FOMO, alerta innecesaria y destruye la credibilidad del peritaje técnico. Un precio de liquidación por desgaste mecánico no es una oportunidad; es simplemente su valor residual real.
* **Cómo se construyó**:
  * Se diseñó una regla bicondicional estricta: `descuento_pvp >= 50%` **Y** `nota >= 9.0`.
  * Solo cuando ambos criterios se cumplen simultáneamente, el notificador (`notifier.py`) dispara la cabecera destacada: `💥🏷️ ¡MEGA CHOLLO e-MTB DETECTADO! (-XX% vs PVP)` y el badge `💥 *MEGA CHOLLO*`.
  * Si la bicicleta acumula un descuento masivo (≥ 50%) pero su nota pericial es `< 9.0`, el sistema la degrada automáticamente a **oferta normal** (`🚵‍♂️ Nueva oportunidad...` o `📉 Bajada de precio`), manteniendo la línea informativa de fábrica (`🏷️ PVP Original: ~XXXX €~ (-XX% | Ahorro: -XXXX €)`) sin estridencias alarmistas.
  * Se incorporó el conteo de Mega Chollos en el Heartbeat diario y la bonificación pericial en `evaluator.py`.

### 14. Segmentación Sonora en Telegram (`disable_notification`): Silencio Operativo vs Alerta Sonora Prioritaria
* **Por qué**: Recibir notificaciones con sonido o vibración todos los días a las 12:00 por ofertas normales de catálogo o por el pulso de diagnóstico diario (Heartbeat) provoca fatiga de alertas (*alert fatigue*) y desensibilización. Si el móvil suena por cualquier bicicleta de rutina, el usuario termina silenciando el canal completo de Telegram y perdiendo las verdaderas oportunidades excepcionales.
* **Cómo se construyó**:
  * Se integró el parámetro nativo `disable_notification: True` de la Telegram Bot API para todas las ofertas estándar de catálogo y para el mensaje diario de diagnóstico Heartbeat en `notifier.py`.
  * La función pericial `es_mega_chollo(bici, nota)` actúa como árbitro centralizado: si y solo si una e-MTB alcanza la excelencia pericial (`nota >= 9.0`) con descuento masivo de liquidación (`>= 50% vs PVP nuevo`), se despacha con `disable_notification: False` (activando el timbre y la vibración sonora prioritaria en el móvil).
  * El comportamiento es configurable de forma reactiva mediante `TELEGRAM_SILENCIAR_OFERTAS_NORMALES` en `.env` / `config.py` y admite anulación manual mediante el parámetro `silencioso: Optional[bool]` en `enviar()`.

### 15. Rotación Dinámica de Alternativas en Análisis Consecutivos (Top 3 Idéntico -> Bloque 4-6)
* **Por qué**: En ejecuciones consecutivas del buscador o en días sucesivos con baja rotación de stock en las tiendas, el Top 3 de oportunidades óptimas suele mantenerse invariable. Volver a notificar exactamente las mismas 3 bicicletas satura la atención y no aporta valor nuevo al comprador; mientras que no notificar nada genera incertidumbre sobre qué otras opciones interesantes existen en el catálogo.
* **Cómo se construyó**:
  * **Persistencia de ejecuciones en SQLite (`db.py`)**: Se creó la tabla `analisis_ejecuciones` (`id`, `fecha`, `top3_ids`, `enviados_ids`, `offset_usado`, `repetido`) que almacena la huella exacta del Top 3 de cada análisis.
  * **Preservación íntegra del pool de candidatas (`main.py`)**: Se refactorizó `_recolectar_oportunidades()` para que devuelva la totalidad de candidatas aptas ordenadas por estricta prioridad (estrictas nuevas -> estrictas conocidas -> respaldo nuevas -> respaldo conocidas), eliminando el truncamiento prematuro a 3 unidades que impedía acceder a los puestos 4, 5 y 6.
  * **Cálculo de rotación por offset cíclico**: Si `ultimo_analisis["top3_ids"] == top3_actual_ids` y existen más de 3 opciones en catálogo, el orquestador avanza automáticamente el offset (`offset_a_usar = 3`), seleccionando las alternativas posicionadas en los puestos #4, #5 y #6 (`oportunidades[3:6]`). Si se vuelve a ejecutar sin cambios, continúa rotando o cicla elegantemente.
  * **Cabecera contextual en Telegram (`notifier.py`)**: Cuando se detecta repetición, el formateador antepone un banner informativo en cada ficha:
    ```markdown
    🔄 *Top 3 sin cambios respecto al análisis anterior*
    💡 _Exponiendo siguiente mejor alternativa #4 del catálogo:_
    ```
  * **Diagnóstico en Heartbeat**: El pulso operativo diario de Telegram reporta la rotación activa con el rango de posiciones expuestas (`🔄 Rotación activa: Top 3 idéntico (exponiendo #4 a #6)`).

### 16. Integración de Wallapop Geolocalizado (Fuenlabrada +50 km) y Peritaje Honesto de Particulares
* **Por qué**: Ampliar el alcance más allá de las 4 tiendas profesionales permite detectar e-MTB de gama alta puestas a la venta por particulares en el entorno cercano (50 km alrededor de Fuenlabrada) a precios muy competitivos (ej. `BH iLynx Race Carbon` por 2.000 €), conservando exactamente los filtros estrictos (`Talla M`, doble suspensión, `> 500 Wh`, `< 21 kg`, `2.000-3.300 €`) sin mezclar envíos lejanos ni ofertas urbanas.
* **Cómo se construyó**:
  * **API de búsqueda por subcategoría (`scrapers/wallapop.py`)**: Consulta `/api/v3/search` con `source="quick_filters"`, `category_id="17000"`, `subcategory_ids="10215"` (Bicicletas eléctricas), coordenadas de Fuenlabrada (`40.2842, -3.7942`), `distance_in_km=50` y rango `2.000-3.500 €` (cubre también la Zona de Vigilancia).
  * **Guardia geográfica Haversine**: Descarta cualquier ítem cuya coordenada supere los `50.0 km` reales aunque Wallapop lo inyecte con promoción nacional (`bump: country`).
  * **NLP sobre descripción libre + Visión IA sin SPA**: Reutiliza los extractores de `enriquecedor_web.py` (mejorados para `t.M`, `size M`, Specialized `S3`, `M/L -> ML`, `540w`, `extender 160w`) sobre título y descripción. Si falta `km`, `enriquecer_bici` inspecciona directamente las URLs de `bici.imagenes` mediante Gemini Vision sin intentar scrapear el HTML Next.js vacío de `es.wallapop.com/item/...`.
  * **Transparencia de garantía (`garantia_anos=0`)**: Distingue vendedores particulares (`has_warranty=False`, `is_refurbished=False` -> `garantia_anos=0`) de tiendas verificadas en Wallapop (`1` año), reflejando `"Sin garantía comercial (particular)"` y la ubicación exacta (`📍 Ubicación: Ciudad (X.X km)`) en `notifier.py` y en `gemini_classifier.py`.

### 17. Deduplicación Inter-Portal, Endurecimiento de Filtros Wallapop/AL y Caché DuckDuckGo
* **Por qué**: Tras integrar Wallapop se detectaron tres fricciones en producción: (1) tiendas como Buhobike republicaban sus mismas bicis en Wallapop exactamente al mismo precio, duplicando alertas u ocultando opciones reales; (2) modelos genéricos de aluminio como `Ghost E-ASX 160 Advanced AL` y títulos vagos (`"Bicicleta Eléctrica BH 237 km"`) o urbanos (`Orbea Diem 10`) se colaban en el análisis; (3) consultar DuckDuckGo sin caché previa tras el orden antiguo disparaba la corrida a ~440–580 segundos.
* **Cómo se construyó**:
  * **Deduplicación cruzada inter-portal (`db.py`, `main.py`)**: `tokens_titulo_dedup` normaliza ruido de anuncio extrayendo explícitamente talla (`talla`/`size`) antes que palabras genéricas y preservando versiones numéricas de modelo (`8.4` vs `8.6`). En `main.py`, `pasa_filtros_estrictos` corre antes de `deduplicar_inter_portal` (evitando que una tienda Talla `L` tape un clon Talla `M`), `deduplicar_inter_portal` verifica compatibilidad de disponibilidad/talla dentro de un margen `±25 €`, y los clones de Wallapop equivalentes a registros ya notificados en `bicis_enviadas` se omiten totalmente.
  * **Fronteras estrictas de modelo y material (`scrapers/wallapop.py`, `gemini_classifier.py`)**: En Wallapop se descartaron urbanas (`diem`, `vibe`, `gain`, etc.), títulos genéricos sin confirmación de amortiguador ni modelo doble, y se reemplazó la lista de subcadenas por el regex con fronteras de palabra `_MODELOS_DOBLE_RE` + normalización `² -> 2` (`Focus JAM²`, `THRON²`), evitando falsos positivos con `"trail"`, `"llevo"`, `"volumen"`, `"riser"` o `"doble pared"`. En `gemini_classifier.py`, `AL` solo se detecta con mayúsculas sobre texto crudo excluyendo frases españolas (`"al 98%"`, `"al día"`), se acotó `CATALOGO_EMTB` (`orbea rise m10/m20/...` sin `"orbea rise m"` que capturaba `"Orbea Rise Motor"`) y se añadió `ghost e-asx` (`24.2 kg Aluminio`).
  * **Caché resiliente de DuckDuckGo (`scrapers/enriquecedor_web.py`)**: Reordenado el catálogo local antes de DuckDuckGo, filtradas consultas sin modelo específico (`_es_consulta_web_especifica` con normalización Unicode NFD) y blindado `completar_desde_duckduckgo` (`ddg_v2:`) con lock por clave (`_obtener_lock_ddg`), extracción incondicional de `peso_kg`, `ano` y `suspension_trasera` sin envenenamiento parcial y sin cachear fallos HTTP/anti-bot (`""`, `anomaly-modal`), reduciendo el tiempo total en vivo a **115.3s**.

### 18. Entrega por Página (1 por Portal) con Rotación Ping-Pong (`#1 -> #2 -> #1`)
* **Por qué**: Al ordenar el catálogo entero priorizando solo bicis no notificadas previamente (`estrictas_nuevas > estrictas_conocidas`) y recortar globalmente a `[:3]`, los anuncios nuevos de Wallapop (`6.5/10`) expulsaban del Telegram mejores oportunidades vigentes de Upway (`8.0/10`), Bike Ocasión o Buhobike, dando la falsa impresión de que solo buscaba en Wallapop.
* **Cómo se construyó**:
  * **Ranking por calidad real (`main.py`)**: `_recolectar_oportunidades` y `clave_orden_estrictas` ordenan primero por salud mecánica verificada (`km is not None and km <= 4000`), ausencia de Línea Roja/anuncio genérico, modalidad (`XC > Light e-MTB > Trail`), nota pericial y menor peso, dejando la novedad solo como desempate final.
  * **Selección por portal (`seleccionar_por_portal`, `db.py`)**: Elige exactamente **1 mejor bicicleta por cada portal** con stock apto (`Wallapop`, `Bike Ocasión`, `Upway`, `Buhobike`, `Mammoth`). Si la `#1` real de un portal no cambió desde la corrida anterior: el **Día 2** expone la `#2` válida (nunca anuncios genéricos descartados `<= 4.5`), y el **Día 3** retorna a la `#1` confirmando que sigue liderando ese portal. El estado (`estado_portales`) solo avanza para portales cuyo envío Telegram tuvo éxito y no se borra ante corridas vacías.

### 19. Perito Mecánico Escéptico y Estricto v2 (`gemini_classifier.py`, `models.py`, `scrapers/wallapop.py`)
* **Por qué**: Los anuncios genéricos de Wallapop sin marca/modelo (`"BICI MONTAÑA ELECTRICA DOBLE CARBONO NUEVA"`) o contradicciones (`"NUEVA"` con >50 km) alcanzaban notas altas (`8.5/10`), y motores Full Power + `>= 625 Wh` recibían estimaciones de peso optimistas (`< 21 kg`).
* **Cómo se construyó**:
  * **Reglas anti-alucinación y física realista (`_es_anuncio_generico_sin_modelo`, `_detectar_contradiccion_nueva`, `_es_motor_full_power`, `_es_excepcion_ligera`)**: Prohibido inventar componentes no declarados (`-1.5 pts` si faltan); las e-MTB Full Power (`>= 625 Wh` o batería sin confirmar) no pueden bajar de `22.5 kg` salvo excepciones ligeras explícitas (`Orbea Rise`, `BH iLynx Race/Trail Carbon`, `Cannondale Moterra SL`, `Amflow PL Carbon`, `Mondraker Neat/Dune >=500Wh`, `Pivot Shuttle SL >=500Wh`), con clamp post-Gemini.
  * **Corrección estricta de motores**: `BH iLynx Race/Trail` sin `+` fijado a `BH 2EXMAG` (cerrado), `BH iLynx+` fijado a `Shimano EP801` (abierto), `Orbea Rise 2021-2022` a `Shimano EP8-RS`, `2025+` a `Shimano EP801-RS Gen2`, y Bosch marcado como dependiente de taller oficial (no muestra SoH/ciclos en app de usuario).
  * **5 Líneas Rojas y rúbrica sin bonos (`perito_v5`)**: Base `10.0` con 5 ejes estrictos incluyendo **Garantía/Canal** (`tienda España 0.0`, `extranjera -1.0`, `particular con factura -1.0`, `sin factura -1.5` con extracción `tiene_factura` en Wallapop) y topes: Talla != M (`0.0`), Batería < 500 Wh (`4.0`), Peso > 21.0 kg (`4.0`), Km > 6.000 (`4.5`) y Anuncio genérico (`4.5`), en formato `🧮 Auditoría Pericial`.

### 20. Canal Exclusivo Black Friday (`<= 3.500 €`, `Black_Bike_Beast`) y PVP en Mammoth (`.is__old`)
* **Por qué**: Las ofertas exclusivas de Black Friday en bicis **completamente nuevas (`0 km`) o de exposición (`<= 50 km`)** suelen situarse entre `3.000 €` y `3.500 €` y quedaban descartadas por el techo diario de segunda mano (`3.300 €`), además de que `scrapers/mammoth.py` no capturaba el PVP tachado porque Mammoth usa `<span class="price is__old">` (devolvía `0` bicis con PVP antes del fix vs `28/66` después).
* **Cómo se construyó**:
  * **Pre-filtro y rúbrica dedicada (`pasa_prefiltro_black_friday`, `evaluar_oportunidad_black_friday` en `evaluator.py`)**: rescata unidades nuevas/exposición entre `2.000 €` y `3.500 €` para enriquecimiento único en `_recolectar_oportunidades` sin contaminar el flujo diario (`<= 3.300 €`), exigiendo datos confirmados de **Talla M**, **doble suspensión**, **peso `< 21.0 kg`**, **batería `>= 500 Wh`**, **`km <= 50` sin contradicciones** (`km=None` queda descartado) y **descuento verificado `>= 35%` sobre PVP** (`nota_bf >= 7.5/10`).
  * **Segundo bot independiente y tabla SQLite propia**: configurado mediante `TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` y `TELEGRAM_CHAT_ID_BLACK_FRIDAY` (con fallback a `TELEGRAM_CHAT_ID`), notificador unificado `_enviar_telegram` + `enviar_black_friday` + pulso operativo `enviar_heartbeat_black_friday` en `notifier.py`, informe consolidado automático **Top 3 más interesantes fuera de tope/criterio** (`enviar_informe_respaldo_black_friday` cuando 0 unidades cumplen `<= 3.500 €`) y deduplicación aislada en `bicis_black_friday_enviadas` (`db.py`, con clave `respaldo:` separada para no bloquear futuras alertas estrictas si bajan a `<= 3.500 €`).

---

## Proceso de desarrollo y dificultades encontradas

### Dificultades encontradas y soluciones de ingeniería

| Dificultad | Sitio afectado | Causa técnica | Solución arquitectónica / Estado |
|------------|---------------|---------------|----------------------------------|
| **Odómetro fotografiado vs texto de mantenimiento ("700 km")** | Buhobike | Buhobike no escribe el odómetro en el texto ni en el SKU en ciertas unidades usadas; solo sube una foto del display (ej. 4.237 km). Un regex simple `\d+ km` capturaba el texto de garantía: *"hacerle unos 700 km sin engrasar la cadena con cera al agua"*, asignando falsamente 700 km (10/10). | **Doble capa**: 1) Filtro de contexto negativo en `_extraer_km` que descarta menciones de cadena, cera, engrase, garantía y autonomía. 2) Fallback con Gemini Flash Vision (`_extraer_km_de_imagenes`) que analiza las fotos del display y extrae el odómetro exacto (`4237 km` -> nota 5.5/10). Si no hay dato confirmado, aplica -2.0 pts preventivos. |
| **Bicis castigadas superando a bicis sanas por modalidad** | Todos / Orquestador | `clave_orden_estrictas` ordenaba por `(sin_linea_roja, prioridad_modalidad, nota)`. Una XC con 5.000 km y nota 3.5/10 quedaba #1 sobre bicis Trail/Light sanas de < 2.000 km (7.5/10). | **Escalón de salud mecánica**: se agregó `salud_mecanica = 1 if (nota >= 6.0 and km <= 4000) else 0` como criterio #1 de ordenación, preservando la prioridad XC estrictamente dentro de cada escalón de salud. |
| **Descarte prematuro de bicis ligeras con batería interna < 500 Wh** | Todos (Orbea Rise, BH iLynx, Levo SL) | e-MTBs superligeras con batería interna de 360 Wh o 480 Wh que incluían el Range Extender oficial eran descartadas por filtro S4 (<= 500 Wh) antes del enriquecimiento, o se confundía la mera compatibilidad comercial ("compatible con extender opcional") con la inclusión real. | **Extractor robusto de Range Extender**: 1) Distingue inclusión real (`+`, `incluye`, `con`, `regalo`) de exclusión comercial (`compatible con`, `opcional`, `no incluido`, `por separado`). 2) Suma la capacidad externa al total (`bateria_wh`) para rescatar oportunidades ligeras de 18 kg y > 600 Wh. 3) Bonifica +0.5 pts en relación calidad-precio y lo refleja en Telegram. |
| **Capacidad efectiva degradada vs capacidad nominal en Upway** | Upway | Upway publica frases como *"conserva el 89 % de su capacidad original de 750 Wh, es decir, 670 Wh"*. Si el extractor tomaba los Wh efectivos degradados en una batería de 540 Wh al 90% (~486 Wh), la bici caía falsamente en el filtro S4 (`<= 500 Wh`). | **Separación Nominal vs SoH**: `_extraer_bateria` prioriza `"capacidad original de XXX Wh"` para conservar la capacidad nominal en `bateria_wh`, mientras `_extraer_salud_bateria` guarda el `% SoH` y los ciclos de carga para evaluarlos en el Perito Mecánico Senior (`>=92%: +0.5`, `80-84%: -1.0`, `<80%: -2.5`). |
| **Bicicletas "Reservadas" o "Agotadas" infiltradas en el Top 3** | Bike Ocasión / Buhobike / Upway / Mammoth | Las tiendas mantienen publicadas las fichas de unidades reservadas o recién vendidas por posicionamiento SEO. | **Filtro S0 en doble barrera**: `BaseScraper.es_tarjeta_no_disponible` descarta tarjetas con badges/clases de reserva o sin stock en los 4 scrapers, y `_extraer_disponibilidad_ficha` valida botones y etiquetas de ficha sin caer en falsos positivos (*"¿Quieres reservarla?"*). |
| **Motor separado en etiquetas `Marca` y `Modelo` + Fechas de entrega como año** | Upway / Mammoth | Upway estructura el motor como `Marca: Shimano Modelo: EP800` (no adyacente), y Mammoth incluye `"Entrega estimada 12 nov. 2026"` que se interpretaba como año del modelo `2026`. | **Regex estructurados con contexto**: `_extraer_motor` soporta `Marca: X ... Modelo: Y` en Upway, y `_extraer_ano` prioriza etiquetas explícitas e ignora contextos de entrega/envío/garantía. |
| **Confusión de motores en gama BH (BH 2EXMAG vs Shimano EP801)** | Bike Ocasión / Buhobike | Los anuncios de `BH iLynx Race/Trail` e `iLynx+` a veces omiten el modelo exacto del motor. Ambos comparten chasis similar pero la serie `iLynx+` monta **Shimano EP801** (diagnóstico abierto, pero con batería/centralita BH) mientras que la serie `iLynx Race/Trail` monta el motor propietario **BH 2EXMAG**. | **Desambiguación en catálogo técnico (`gemini_classifier.py`)**: Se separaron las firmas de catálogo de `bh ilynx+` (Shimano EP801) y `bh ilynx race/trail` (BH 2EXMAG), manteniendo la penalización de -1.0 pt en BH por ecosistema de batería cerrado que impide extraer informe PDF oficial de salud de celdas. |
| **Archivo `logs/buscador.log` vacío (0 bytes)** | Orquestador / `scraper_base.py` | `scraper_base.py` ejecutaba `logging.basicConfig()` al importarse antes de `main.py`, haciendo que Python ignorara silenciosamente el `FileHandler` configurado posteriormente en `main.py`. | Se eliminó `logging.basicConfig()` de `scraper_base.py` y se añadió `force=True` en `main.py`. |
| **URL de categoría 404** | Bike Ocasión | La URL original (`bicicletas-electronicas/doble-suspension/`) devolvía 404. Se inspeccionó el menú y se encontró la URL correcta: `bicicletas-electricas-de-montana-doble-suspension-2020`. | Selectores y URLs actualizados tras inspección en vivo. |
| **Protección anti-baneo (503)** | Buhobike | `Fetcher` HTTP devuelve 503 por desafío JS de Cloudflare. | `StealthyFetcher` con `solve_cloudflare=True` y `usar_stealth_directo=True`. |
| **Incompatibilidad TextHandler vs BeautifulSoup** | Bike Ocasión | `page.html_content` de Scrapling es un `TextHandler` (subclase de `str`). | Se normaliza con `str(html)` en `scraper_base.py`. |
| **Pérdida de corrida por suspensión del PC** | Task Scheduler | A las 12:00 el PC estaba suspendido y Task Scheduler marcó `NumberOfMissedRuns: 1`. | Configurado `WakeToRun: True`, `StartWhenAvailable: True` y ejecución en batería en la tarea `BuscadorBiciOcasion` mediante PowerShell. |
| **Bloqueo de archivo SQLite en Windows (`WinError 32`)** | Base de datos / Tests | En Windows, abrir conexiones SQLite mediante `with sqlite3.connect(...)` sin invocar `.close()` mantiene abierto el descriptor del archivo temporal hasta que el recolector de basura lo destruye, causando `PermissionError: [WinError 32]` en los tests. | Se encapsuló la limpieza de bases de datos temporales en bloques `try...except PermissionError` para garantizar tests atómicos y confiables. |
| **Ambigüedad entre milímetros de suspensión vs ruedas, bielas o discos** | Enriquecedor / Evaluador | Regex ingenuos sobre `\d+ mm` capturaban diámetros de rueda (`29" / 622 mm`), discos de freno (`180 mm`, `203 mm`) o longitud de biela (`170 mm`, `175 mm`), contaminando el recorrido. | `_extraer_recorrido` restringe la búsqueda a prefijos explícitos (`recorrido`, `travel`, `horquilla`, `suspensión`, `amortiguador`) o marcas reconocidas (`Fox 34`, `RockShox SID/Pike`, `Marzocchi`), validando el rango estricto entre 100 y 180 mm. |
| **Trazabilidad de catálogo sin penalizar latencia de scraping** | Orquestador / Base de datos | Si para registrar el historial de precios tuviéramos que entrar a las 320 fichas de detalle, la búsqueda tardaría >12 minutos por corrida. | `registrar_en_catalogo` se nutre directamente del flujo de pre-filtrado en memoria de los 4 scrapers paralelos, manteniendo la corrida completa en ~51 segundos. |
| **Scrapling 0.5 ProxyRotator sin método `.add()` e inicialización posicional** | BaseScraper / Enriquecedor | En Scrapling 0.5 `ProxyRotator()` no admite constructor vacío ni tiene método `.add()`; exige `proxies: List[str]` en `__init__`. Además `FetcherSession` guarda `_proxy_rotator` como atributo privado y no público. | Se diseñó la factoría `crear_proxy_rotator(proxies, rotacion)` con sanitización de comillas/líneas en `config.py`, inyectando el rotador directamente en los argumentos de `FetcherSession`, `StealthyFetcher.fetch` y `Fetcher.get`. |
| **Tracking accidental de archivo dinámico `logs/buscador.log` en Git** | Repositorio / Git | Aunque `logs/` figuraba en `.gitignore`, `logs/buscador.log` había sido indexado en commits anteriores, ensuciando los diffs y el árbol de trabajo en cada corrida. | Se desindexó mediante `git rm --cached logs/buscador.log` manteniendo el archivo local y limpiando los commits de producción. |
| **Timeout de inferencia individual en odómetros por imagen** | Enriquecedor / Visión IA | `gemini-flash-latest` con thinking tardaba >15s por foto en llamadas secuenciales, disparando timeouts en galerías de 6 fotos. | Agrupación de la galería completa en un único lote multimodal hacia `gemini-3.5-flash-lite`, resolviendo toda la galería en 3–5 segundos. |
| **Peso con embalaje (22 kg) enmascarando peso real en Buhobike** | Buhobike / Enriquecedor | Buhobike mezcla el peso de envío (`22,000 Kg`) con el peso de báscula (`19,57 Kg`), provocando descarte por filtro S3 (> 21 kg). | Parseo estructurado previo de `table.caracteristicas-tecnicas-2-tablas` y `#product-details`, extrayendo peso neto de báscula antes de limpiar el DOM. |
| **Extracción de PVP original nuevo vs precio de ocasión** | Upway / Bike Ocasión / Mammoth / Buhobike | Las tiendas muestran en la misma tarjeta o ficha el precio actual y el PVP original de fábrica tachado (ej. *"2.499 € 6.000 € nuevo"* en Upway, `<del>` o `.price-before-discount`). Un regex simple capturaba el primer valor o confundía el descuento con el precio real de venta. | Implementado extractor específico `_parsear_pvp_original` que compara los montos adyacentes mayores al precio ofertado, persistiendo `pvp_original` en SQLite para calcular el descuento real vs nuevo (~57% en Upway). |
| **Extenders opcionales vs batería principal en Mammoth (`EnergyPak 625` + extender compatible)** | Mammoth / Enriquecedor | Fichas técnicas en Mammoth declaran cadenas compuestas como *"Batería: EnergyPak Smart 625EnergyPak Plus 250Wh range extender compatible"*. Un extractor ingenuo tomaba los 250 Wh o sumaba una batería opcional no incluida. | Aislamiento de capacidades comerciales de catálogo sin 'Wh' explícito (`EnergyPak 625`, `PowerTube 750`, etc.) y filtrado estricto que descarta menciones adyacentes de compatibilidad comercial (`compatible`, `opcional`). |
| **Telemetría de bicis nuevas (km=0) y baterías sustituidas** | Mammoth / Upway / Enriquecedor | Unidades nuevas de liquidación (km=0 con 3 años de garantía) o de ocasión con batería a estrenar ("Batería: Reemplazada") no publican informe de degradación en texto, arriesgando quedar sin telemetría o penalizadas. | Detección contextual de batería sustituida/a estrenar fijando `SoH: 100%` y `0 ciclos`, y normalización automática para bicis con `km=0` y `garantia_anos >= 2`, otorgando la bonificación de +0.5 pts en el Perito Mecánico Senior. |
| **Heartbeat operativo diario sin saturar alertas en Telegram** | Notificador / Orquestador | En días donde ninguna e-MTB supera el corte de oportunidad (nota >= 8.0), el usuario no tenía certeza de si el cron de las 12:00 corrió con éxito, se suspendió o fue bloqueado por Cloudflare. | Implementado `enviar_heartbeat` (`formatear_heartbeat`) que reporta duración, conteo por tienda, candidatas aptas analizadas, tamaño del radar activo y unidades en vigilancia diaria con flag `TELEGRAM_HEARTBEAT`. |
| **Migración no destructiva de base de datos SQLite en producción** | Base de datos (`db.py`) | Añadir `pvp_original` a la tabla `historial_catalogo` en entornos con bases de datos preexistentes causaba `OperationalError` al no existir la columna. | Migración preventiva idempotente con `ALTER TABLE historial_catalogo ADD COLUMN pvp_original REAL` encapsulada en `try...except` durante la inicialización de la conexión. |
| **Falsos positivos de "Mega Chollo" en bicis desgastadas (nota < 9.0)** | Notificador / Orquestador | Un descuento >50% vs PVP original en una bicicleta con alto kilometraje o batería mermada (ej. nota 3.5 o 5.5/10) activaba la cabecera `💥 ¡MEGA CHOLLO!`, generando falso FOMO cuando en realidad se trataba de un precio de liquidación acorde a su desgaste. | Se aplicó una regla bicondicional estricta: `descuento_pvp >= 50%` Y `nota >= 9.0`. Si la nota es inferior a 9.0, se degrada a oferta normal mostrando el PVP original a título informativo sin cabecera alarmista. |
| **Fatiga de alertas y ruido sonoro diario en Telegram** | Notificador / UX de usuario | Si el bot activa timbre y vibración en el móvil todos los días a las 12:00 para ofertas rutinarias o heartbeats de diagnóstico, el usuario silencia el canal y se desensibiliza, ignorando alertas críticas. | Segmentación acústica nativa en Telegram Bot API: `disable_notification=True` para ofertas estándar y Heartbeat diario, reservando el timbre sonoro y vibración exclusivamente para verdaderos Mega Chollos (`nota >= 9.0` y `dto >= 50%`). |
| **Repetición estéril del Top 3 en análisis consecutivos** | Orquestador / Base de datos / Notificador | Al ejecutar búsquedas consecutivas o en períodos sin cambios de catálogo, notificar el mismo Top 3 no aporta valor, mientras que silenciarlo oculta alternativas viables. Además `_recolectar_oportunidades()` truncaba el pool a 3 unidades impidiendo acceder a puestos inferiores. | Refactorizado `_recolectar_oportunidades()` para preservar todo el catálogo apto; persistencia de la huella en tabla `analisis_ejecuciones` y rotación automática con offset cíclico (#4-#6) con cabecera de aviso contextual en Telegram (`🔄 Top 3 sin cambios respecto al análisis anterior`). |
| **Paginación híbrida de Wallapop (`items=[]` con `next_page=True`) y parámetros de categoría** | Wallapop (`scrapers/wallapop.py`) | Consultar `/api/v3/search` sin keywords con `category_ids=17000` devolvía coches (`category_id=100`); además el motor de blending de Wallapop devuelve páginas intermedias vacías (`items=[]` en la pág. 3) manteniendo `meta.next_page`, lo que cortaba la extracción en solo 5 ítems. | Migrado a `source="quick_filters"` + `category_id="17000"` + `subcategory_ids="10215"` (Bicicletas eléctricas), paginando hasta agotar `next_page` (24 páginas / 592 anuncios en vivo) con guarda Haversine `<= 50 km` contra anuncios `bump: country`. |
| **HTML SPA sin hidratar y falsos negativos en NLP libre de Wallapop** | Wallapop / `enriquecedor_web.py` | La ficha web `es.wallapop.com/item/...` es Next.js SPA (`imgs=0` en Scrapling estático); además anuncios reales incluían `"t.M"`, `"Talla S3"`, `"M/L"`, `"540w"`, `"3000km ... cadena a estrenar"` (bloqueado por ventana `-65/+65` de `'cadena'`) o `"batería interna 320Wh + extender 160w incluido"` (capturando `320` en lugar de `160`). | En Wallapop `enriquecer_bici` lee directamente `bici.imagenes` mediante Gemini Vision sin scrapear el SPA HTML; `_extraer_talla` soporta `t.M`, `S1-S6` y compuestas (`M/L -> ML`); `_extraer_range_extender` ignora capacidades precedidas por `interna/principal`; `_extraer_km` refina la lista de bloqueo de mantenimiento de cadena. |
| **Clones de tiendas en Wallapop y falsos positivos de aluminio / doble suspensión** | `db.py` / `main.py` / `wallapop.py` / `gemini_classifier.py` | Tiendas oficiales (ej. Buhobike) republicaban las mismas bicicletas al mismo precio en Wallapop (`ORBEA RISE H10`, `MONDRAKER DUSK R`, `BH ILYNX RACE`). Además `Ghost E-ASX 160 Advanced AL` se clasificaba como Carbono (`18.6 kg`), `'al 98%'` disparaba aluminio y subcadenas en Wallapop (`trail`/`llevo`/`volumen`/`riser`) daban falsos positivos de doble suspensión. | `deduplicar_inter_portal` y `fue_enviada_equivalente` omiten clones Wallapop dentro de `±25 €` (tras pre-filtrar talla `M`), conservando versiones numéricas (`8.4` vs `8.6`). `_MODELOS_DOBLE_RE` usa `\b` + `²->2`, `AL` solo matchea mayúsculas con lookahead y `orbea rise m` ambiguo fue acotado. |
| **Latencia ~580s en DuckDuckGo, caché parcial y cacheo de errores HTTP** | `scrapers/enriquecedor_web.py` | Consultar DuckDuckGo antes del catálogo local y sin caché previa bloqueaba ~440–580s; además extraer solo campos `None` envenenaba la caché para bicis posteriores y los fallos HTTP/timeouts (`""`) quedaban cacheados 7 días. | Reordenado `completar_con_catalogo` antes de DuckDuckGo, añadido filtro de especificidad (NFD), lock por clave (`_obtener_lock_ddg`), extracción incondicional (`ddg_v2:`) de los 3 campos críticos y exclusión de respuestas vacías/anti-bot (`anomaly-modal`), bajando la corrida total a **115.3s** (y **31.9s** en pasadas cacheadas). |
| **Cupos globales saturados por Wallapop ocultando tiendas profesionales** | `main.py` / `db.py` / `notifier.py` | Priorizar globalmente `estrictas_nuevas` sobre `estrictas_conocidas` y recortar a `[:3]` hacía que 3 anuncios nuevos de Wallapop (`6.5/10`) expulsaran bicis mejores ya vistas de Upway (`8.0/10`) o Bike Ocasión. | `seleccionar_por_portal` entrega **1 mejor opción de cada página** con stock apto sin degradar bicis ya conocidas frente a inferiores, con rotación diaria por portal `#1 -> #2 -> #1` persistida en `estado_portales` solo si el envío Telegram acierta. |
| **Falsos positivos de genéricas/contradicciones y pesos irreales en Full Power** | `gemini_classifier.py` / `models.py` / `wallapop.py` | Anuncios vagos (`"BICI MONTAÑA ELECTRICA DOBLE CARBONO NUEVA"`), contradicciones `"NUEVA"` + km elevados, y baterías `>= 625 Wh` con peso optimista `< 21 kg` inflaban notas hasta `8.5/10`. | Nuevo **Perito Escéptico v2** (`perito_v5`): 5 Líneas Rojas (genérica `<= 4.5`, Talla `0.0`, `<500Wh 4.0`, `>21kg 4.0`, `>6000km 4.5`), física Full Power `>= 22.5 kg` post-Gemini, corrección `BH iLynx+`/`Orbea Rise`/Bosch, eje Garantía (`tiene_factura` en Wallapop) y aritmética sin bonos positivos. |

| **Segundo bot bloqueado (`403`) hasta `/start` + Markdown v1 roto con `_`** | `notifier.py` / `.env` / Telegram | Telegram prohíbe a un bot nuevo (`@BlackBikeBeast_bot`) iniciar chat privado (`getUpdates = 0`) hasta que el usuario pulsa `/start`; además escribir `Black_Bike_Beast` dentro de `parse_mode='Markdown'` interpretaría `_Bike_` como cursiva. | Validación `getMe`/`getUpdates`, variables separadas (`TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` y `TELEGRAM_CHAT_ID_BLACK_FRIDAY` con fallback a `TELEGRAM_CHAT_ID`), texto libre de guiones bajos (`Black Bike Beast`) y `enviar_heartbeat_black_friday` dedicado para confirmar pulso vivo. |
| **PVP tachado invisible en Mammoth (`0/66` vs `28/66`) y orden DOM** | `scrapers/mammoth.py` | El selector antiguo (`.card-price-old / del`) ignoraba `<span class="price is__old">` dentro de `.card-product-price`, dejando `pvp_original=None`; además un selector unión sin `:not(.is__old)` en `precio_el` corría riesgo de coger el precio viejo según el orden del DOM y dejar `0.0` al fallar el parseo. | Añadido `.is__old, .price.is__old` con limpieza de `<= precio` / `0.0` a `None` (desbloqueando `28/66` bicis con PVP real en vivo) y selección secuencial en `precio_el` excluyendo `:not(.is__old)`. |
| **Contaminación dedup `>3.300 €` y bypass de peso estimado / `suspension_trasera=None`** | `main.py` / `evaluator.py` / `gemini_classifier.py` | Unir `pre_aptas` y extras `>3.300 €` antes de `deduplicar_inter_portal` dejaba que una bici oficial no apta en flujo diario ocultara una Wallapop elegible; además `enriquecer_y_valorar_bici` rellenaba `peso_kg` con heurística/IA sin marca de origen y `suspension_trasera=None` pasaba `_pasa_requisitos_base_mecanicos`. | Deduplicación separada (`pre_aptas_dedup` vs `bf_extra_dedup`), marca `_peso_estimado = True` si no hubo dato empírico (ficha, catálogo o DuckDuckGo) rechazada en `evaluar_oportunidad_black_friday`, y exigencia explícita `suspension_trasera == "si"`. |
| **Aislamiento de dedup entre Top 3 de respaldo (`>3.500 €`) y alertas futuras `<=3.500 €`** | `db.py` / `main.py` | Registrar el informe Top 3 fuera de tope con su `bici_id` real en `bicis_black_friday_enviadas` habría bloqueado alertas estrictas futuras si la bici bajaba a `<=3.500 €` o suprimido clones equivalentes (`±25 €`) de otro portal; además `with sqlite3.connect` no cerraba descriptores en Windows. | Registro bajo prefijo `respaldo:{bici_id}` y filtro `AND bici_id NOT LIKE 'respaldo:%'` en `_fue_enviada_equivalente_en_tabla`, más `@contextmanager` con `timeout=30.0`, `WAL` y `conn.close()` en `db.py`. |

---

## Estado actual y próximos pasos

### Fotografía del estado actual (20/11/2026)
- **Canal diario multi-portal (5 fuentes, entrega por página)**: **Wallapop** (geo-radio `<= 50 km`), **Bike Ocasión** (`180` bicis), **Mammoth Bikes** (`66` bicis, ahora con `28` PVP originales detectados), **Buhobike** (`49` bicis) y **Upway** (`22` bicis) — en la corrida `--once` de hoy procesó **118 candidatas diarias aptas**, notificó `4` opciones (`1 por portal`: *Wallapop*, *Upway*, *Buhobike* y *Bike Ocasión*) + Heartbeat diario.
- **Canal exclusivo Black Friday (`@BlackBikeBeast_bot`) + Respaldo Top 3**: Activo en paralelo hasta `3.500 €` (`km <= 50`, Talla M, `< 21,0 kg` empírico, `>= 500 Wh`, doble confirmada, `>= 35% dto PVP`, `nota_bf >= 7,5/10`). Cuando `0` unidades cumplen todo el estricto en presupuesto, dispara automáticamente un informe consolidado **Top 3 más interesantes fuera de tope/criterio** (`Cannondale Moterra SL 2` `4.549,35 € -35%`, `Orbea Rise LT H10 2026` `4.499 € -27,4%`, `BH iLynx Trail Carbon 8.6` `2.449 € -62,9%` enviados hoy en vivo) más su propio pulso `enviar_heartbeat_black_friday`.
- **Perito Mecánico Escéptico y Estricto v2 (`perito_v5`)**: Operativo tanto en Gemini Flash como en motor autónomo determinista con 5 ejes sin bonos (`Km`, `Peso`, `Motor/Bat`, `Garantía/Vendedor`, `Precio/Componentes`), detección de contradicciones (`"NUEVA" + >50 km`), bloqueo de genéricas `<= 4.5`, física anti-optimismo Full Power `>= 22.5 kg` y extracción de `tiene_factura` en Wallapop.
- **Rotación ping-pong `#1 -> #2 -> #1` por portal (`seleccionar_por_portal`)**: Si la `#1` de un portal no varía respecto al análisis anterior, expone el `#2` al día siguiente y vuelve a confirmar el `#1` al tercer día, conservando `estado_portales` en SQLite (`analisis_ejecuciones`).
- **Deduplicación inter-portal, aislamiento SQLite y caché DuckDuckGo**: Activa deduplicación separada por flujo (`pre_aptas` diario, `bf_extra` estricto y `bf_respaldo` fuera de tope), tabla dedicada `bicis_black_friday_enviadas` con prefijo `respaldo:` excluido de clones, conexiones cerradas vía `@contextmanager` (`WAL`) y caché `ddg_v2:` segura.
- **Radar de mercado y reportes**: `docs/radar_mercado.md` actualizado hoy en vivo (**222 unidades activas**, **2.6 días** de stock medio, **17 rebajas activas** con Mammoth mostrando `~26% vs PVP`, **96 unidades en Zona de Vigilancia**) y modo CLI `python main.py --stats`.
- **Resiliencia de red**: `ProxyRotator` nativo en `scraper_base.py` y `enriquecedor_web.py` configurable vía `PROXY_LIST` en `.env`.
- **Suite de tests y verificación**: `python test_buscador.py` 100% en **GREEN** tras la última edición y auditoría independiente sin hallazgos abiertos.
- **Automatización y logs**: Tarea `BuscadorBiciOcasion` activa a las 12:00 diarias con despertar automático (`WakeToRun: True`), ignorando `.env`, `*.db` y `logs/buscador.log`.

### Tareas completadas recientemente

- [x] **Canal exclusivo Black Friday (`<= 3.500 €`) + segundo bot (`@BlackBikeBeast_bot`)**: Configuradas credenciales dedicadas en `.env`/`.env.example`, rúbrica dedicada sin alucinaciones de peso ni suspensión, tabla `bicis_black_friday_enviadas`, pulso `enviar_heartbeat_black_friday` e informe automático Top 3 de respaldo cuando no hay chollos en presupuesto.
- [x] **Fix de PVP tachado en Mammoth (`.is__old` / `:not(.is__old)`)**: Desbloqueada la captura real de precios de tarifa y porcentajes de descuento (`28/66` bicis en vivo vs `0/66` previo).
- [x] **Endurecimiento SQLite (`@contextmanager` + `WAL` + `respaldo:%`) y dedup separada en `main.py`**: Cierre explícito de conexiones en Windows e independencia total entre canal diario, canal Black Friday estricto y respaldo Top 3.
- [x] **Endurecimiento preventivo, selección por portal (`#1/#2/#1`) y Perito Escéptico v2**: Desambiguación BH/Rise/Bosch, clones Wallapop/Buhobike, física Full Power `>= 22.5 kg` y entrega justa por portal.

### Plan de trabajo propuesto para mañana (TODOs pendientes)

- [ ] **TODO 0 (Seguridad) — Rotar token de `@BlackBikeBeast_bot` en `@BotFather`**
  - **Objetivo**: Regenerar el token del segundo bot con `/revoke` en `@BotFather` y actualizar únicamente `TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` en el archivo local `.env`, dado que el token inicial quedó registrado en el historial de conversación.
- [ ] **TODO 1 — Scoring de degradación de batería en el evaluador (`evaluator.py`)**
  - **Objetivo**: Incorporar formalmente en el algoritmo numérico de `evaluator.py` la penalización por `bateria_salud_pct` y `bateria_ciclos` cuando estén disponibles, alineándolo con el Perito Mecánico Escéptico v2.
- [ ] **TODO 2 — Blindar rotación `#2` diaria frente a `Línea Roja > 6.000 km` y calibrar tope de batería Black Friday (`480 Wh` vs `500 Wh`)**
  - **Objetivo**: Evitar en `seleccionar_por_portal` que unidades descartadas por `Km > 6.000` (ej. *Orbea Rise H15 XT 7.040 km*, `3.5/10`) ocupen la rotación `#2` cuando existan alternativas sanas, y decidir si para chollos extremos de exposición (ej. *Ghost Path Riot Fazua 480 Wh* al `-61%`/`-67%`) se admite `>= 480 Wh` en el canal Black Friday estricto.
- [ ] **TODO 3 — Dashboard web interactivo o exportación HTML para el Radar de Mercado**
  - **Objetivo**: Desarrollar un visualizador web ligero (o exportación HTML interactiva) para consultar de forma gráfica la rotación de stock, curvas de permanencia y precios del catálogo SQLite.
- [ ] **TODO 4 — Detección de chollos por degradación anómala de precio (Delta diario > 300 €)**
  - **Objetivo**: Añadir badge de alerta reactiva cuando una bicicleta sufra un recorte repentino de precio mayor a 300 € en un solo día, independientemente de su PVP original.

### Dependencias instaladas

- `scrapling>=0.5` (motor principal de scraping)
- `patchright>=1.64` (fork de Playwright usado por Scrapling)
- `browserforge>=1.2` (fingerprint generation)
- `msgspec>=0.22` (serialización rápida)

### Estado final

| Componente | Estado |
|------------|--------|
| Canal exclusivo Black Friday (`<= 3.500 €`, `@BlackBikeBeast_bot`) | ✅ Verificado (alertas estrictas, informe Top 3 fuera de tope y heartbeat en vivo) |
| Scraper Mammoth (`scrapers/mammoth.py`) | ✅ Fix `.is__old` / `:not(.is__old)` activo (`28/66` con PVP en vivo, SoH 100%) |
| Lógica de filtros, Perito Mecánico Escéptico v2 (`perito_v5`), dedup, Telegram | ✅ Verificado (`python test_buscador.py` GREEN + `--once` en vivo) |
| Entrega por página (`1 por portal`) y rotación `#1 -> #2 -> #1` | ✅ Verificado (`estado_portales` en SQLite, 4 portales notificados en vivo) |
| Base de datos SQLite (`bicis_enviadas`, `bicis_black_friday_enviadas`, `WAL`) | ✅ Cierre seguro con `@contextmanager`, dedup separada con `respaldo:` |
| Detección de Mega Chollos (dto >= 50% y Nota >= 9.0) | ✅ Activo en vivo (`Upway BH iLynx Trail Carbon 8.6`, 9.5/10) |
| Segmentación sonora Telegram (silencioso vs prioritario) | ✅ Implementado (`disable_notification` según Mega Chollo / Black Friday) |
| Scraper Wallapop geolocalizado (Fuenlabrada +50 km) | ✅ Verificado en vivo (geo-filtro Haversine `<= 50 km`, extracción `tiene_factura`) |
| Prioridad de modalidad (XC > Light e-MTB > Trail) | ✅ Implementado (`prioridad_modalidad` en `evaluator.py` y `main.py`) |
| Desambiguación de motores BH (BH 2EXMAG vs Shimano EP801) | ✅ Verificado (BH iLynx Race/Trail fijado a 2EXMAG, iLynx+ a EP801 + batería BH) |
| Selectores Bike Ocasión / Buhobike / Upway | ✅ Verificados en vivo (`180` / `49` / `22` unidades extraídas en la corrida de hoy) |
| Enriquecedor web paralelo, caché `fichas_detalle.json` y `ddg_v2:` | ✅ Paralelo (`ThreadPoolExecutor`), `<dt>/<dd>`, telemetría SoH/ciclos y filtro de embalaje |
| Health check, Task Scheduler 12:00, Heartbeat dual y Radar (`--stats`) | ✅ Operativos (`docs/radar_mercado.md` actualizado con `222` unidades en seguimiento) |

---

## Licencia

MIT

---

## Créditos

Desarrollado como asistente de código bajo la identidad **el Gentleman** (Pi-specific coding-agent harness), siguiendo el flujo de desarrollo **Organic Driven Development (ODD)**.
