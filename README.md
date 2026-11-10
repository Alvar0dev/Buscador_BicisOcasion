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
- [Próximos pasos y Roadmap](#próximos-pasos-y-roadmap)
- [Por qué se ha construido así (Arquitectura e Ingeniería de Decisiones)](#por-qué-se-ha-construido-así-arquitectura-e-ingeniería-de-decisiones)
- [Proceso de desarrollo y dificultades encontradas](#proceso-de-desarrollo-y-dificultades-encontradas)
- [Estado actual y TODOs para mañana (Próxima Sesión)](#estado-actual-y-todos-para-mañana-próxima-sesión)
- [Licencia](#licencia)

---

## ¿Qué hace este proyecto?

Este script rastrea diariamente las secciones de e-MTB doble suspensión de cuatro tiendas profesionales de bicicletas con garantía oficial:

- **Bike Ocasión** (bike-ocasion.com)
- **Buhobike** (buhobike.com)
- **Upway** (upway.es)
- **Mammoth Bikes** (mammothbikes.com)

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

## Algoritmo de Nota de Oportunidad (Perito Mecánico Senior)

El sistema opera bajo la **Regla Maestra del Perito Mecánico Senior**: **NUNCA** realiza medias optimistas. La evaluación parte de una nota base de **10.0** y aplica deducciones aritméticas irreversibles y límites por **Líneas Rojas**:

### 1. Penalizaciones por Kilometraje (Factor Crítico)
* **0 a 1.000 km**: -0.0 pts (Estado óptimo de reestreno, desgaste despreciable).
* **1.001 a 2.000 km**: -1.0 pts (Rodada y aceptable; prever mantenimiento de cadena y pastillas).
* **2.001 a 4.000 km**: -2.5 pts (Desgaste medio en transmisión y ciclos de celdas; revisión de holguras).
* **4.001 a 6.000 km**: -4.5 pts (Exige cambio de retenes, revisión de motor y batería mermada).
* **Más de 6.000 km**: **LÍNEA ROJA ACTIVADA**. La nota final **NUNCA puede superar el 4.5/10**, sin importar cuadro o componentes.

### 2. Penalizaciones y Bonificaciones por Peso
* **< 19.0 kg**: +0.5 pts (Bonificación por peso pluma; menor fatiga estructural).
* **19.1 a 20.0 kg**: -0.0 pts (Peso neutro ideal para Light e-MTB).
* **20.1 a 21.0 kg**: -1.5 pts (Límite admisible; mayor inercia y consumo).
* **> 21.0 kg**: **LÍNEA ROJA ACTIVADA**. Nota máxima limitada a **4.0/10**.

### 3. Motor, Centralita, Telemetría SoH y Transparencia de Diagnóstico
* **Shimano (EP8 / EP801 / EP6) o Bosch (Performance Line CX / SX)**: -0.0 pts (Permiten informe PDF pericial oficial mediante Shimano E-Tube PCE02 o Bosch DiagnosticTool 3).
* **Telemetría empírica de Salud de Batería (SoH % y ciclos)**:
  * **SoH ≥ 92%**: +0.5 pts (Celdas auditadas en estado excelente).
  * **SoH 85% a 91%**: -0.0 pts (Degradación química normal).
  * **SoH 80% a 84%**: -1.0 pt (Degradación apreciable de autonomía).
  * **SoH < 80%**: -2.5 pts (Fatiga química severa de celdas).
  * **> 250 ciclos de carga** (sin SoH explícito): -1.0 pt por desgaste acumulado de celdas.
* **Bicicletas BH (iLynx, AtomX, BH 2EXMAG)**: -1.0 pt directo por centralita con software propietario y opaco que impide al comprador extraer un informe veraz en PDF de salud de celdas (SoH) y ciclos.
* **BH 2EXMAG o Brose con > 3.000 km**: -1.5 pts extra acumulativos (total -2.5 pts en motor) por kilometraje elevado a ciegas sin diagnóstico abierto.

### 4. Precio frente a Kilometraje
* **Rango base 2.000 € a 3.000 €**: -0.0 pts.
* **Precio > 3.000 € y kilometraje > 2.000 km**: -1.5 pts (Sobrecoste penalizado frente al desgaste acumulado).

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
- buhobike.com
- upway.es
- mammothbikes.com

**Bajo ningún concepto se incluye código para rastrear plataformas de trato entre particulares** como Wallapop, Milanuncios o foros, ya que no ofrecen garantía mecánica certificada.

---

## Arquitectura modular

El proyecto está separado en módulos con responsabilidad única:

| Archivo | Responsabilidad |
|---------|-----------------|
| `config.py` | Configuración central: URLs objetivo optimizadas, filtros estrictos, credenciales Telegram/Gemini, user-agents rotatorios, proxies (opcional), horario de ejecución. |
| `models.py` | Dataclass `Bicicleta` con todos los campos necesarios para scoring y notificación. |
| `db.py` | Base de datos SQLite: registro de bicicletas ya enviadas, deduplicación por ID y detección de bajadas de precio para re-alerta. |
| `evaluator.py` | Filtros estrictos (S1-S6), algoritmo de Nota de Oportunidad y ordenamiento por prioridad de modalidad (`prioridad_modalidad`: XC > Light e-MTB > Trail). |
| `gemini_classifier.py` | Motor Perito Mecánico Senior (`auditar_perito_mecanico`), catálogo técnico de e-MTB, desambiguación de motores BH (BH 2EXMAG vs Shimano EP801) y clasificador híbrido con Gemini Flash + caché thread-safe. |
| `notifier.py` | Notificador de Telegram vía `requests`, mensaje Markdown con todos los campos requeridos (S9). |
| `scraper_base.py` | Clase base con **motor Scrapling**: `Fetcher` (HTTP con impersonación TLS) → `StealthyFetcher` (navegador stealth con `solve_cloudflare=True`), con `usar_stealth_directo` y salto inmediato ante bloqueos HTTP 403/503 de Cloudflare. |
| `scrapers/bike_ocasion.py` | Adaptador específico para Bike Ocasión. Extrae título limpio (`h3.s_title_block a`), talla, batería, km, marca del motor (`Km / <Marca>`) y doble suspensión directamente de la tarjeta del listado. Paginación de hasta 6 páginas (180+ bicis). |
| `scrapers/buhobike.py` | Adaptador específico para Buhobike con modo stealth directo (`usar_stealth_directo=True`), rastreo combinado de `/3230-electricas-trail-dobles?order=product.price.asc` y `/9448-segunda-mano-montana-electricas`, y extracción en tarjeta de título completo (`img.thumbnail-img[alt]`), talla (`#/...-talla-m`), año y km desde SKU (`KM5000`). |
| `scrapers/upway.py` | Adaptador específico para Upway sobre `/collections/doble-suspension`. Extrae año, kilometraje (`\u202fkm` y `< 5 km`), talla (desde el rango de estatura `1mXX-1mYY`) y doble suspensión directamente de la tarjeta en `< 1s`. |
| `scrapers/mammoth.py` | Adaptador específico para Mammoth Bikes sobre `/bicicletas-electricas-mtb-dobles-rally-xc/c-3104` y `/bicicletas-electricas-mtb-trail-all-mountain-dobles/c-2139`. Extrae precio, tallas en stock (`M`), modalidad XC, año y filtro anti-rígidas directamente de `div.card-content` en `~2.5s`. |
| `scrapers/enriquecedor_web.py` | Enriquecedor web paralelo con caché JSON en disco (`cache/fichas_detalle.json`), extracción de pares `<dt>/<dd>`, limpieza de DOM y regex con bordes de palabra (`\b`) y filtrado de pesos con embalaje. |
| `main.py` | Orquestador: scrape de los sitios → **health check** → pre-filtro → **enriquecimiento paralelo** → auditoría Perito Mecánico Senior → ordenamiento por salud mecánica (`nota >= 6.0` y `km <= 4.000`), Línea Roja y prioridad de modalidad (`XC > Light e-MTB > Trail`) → SQLite → Telegram (`--once` y `--forzar`). |
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
| 11 | **Modo radar de mercado CLI (`python main.py --stats`)** | ✅ Completado | Comando de consola (`--stats` o `--radar`) que resume el catálogo en seguimiento activo: unidades por tienda, precios medios/mínimos de modelos estrella (*Orbea Rise*, *BH iLynx*, etc.), unidades en vigilancia (2.900–3.400 €) y rebajas activas. |

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

### 9. Radiografía de Mercado en CLI (`python main.py --stats`)
* **Por qué**: El usuario y el desarrollador necesitan ver en cualquier momento qué está pasando en el mercado (precios medios de Orbea Rise o BH iLynx, unidades estancadas, oportunidades en zona de vigilancia) sin depender exclusivamente del push diario de las 12:00 ni consultar tablas SQL a mano.
* **Cómo se construyó**: Se añadió la función `mostrar_radar_mercado()` activable mediante el flag `--stats` (o `--radar`), que procesa en tiempo real las 29+ unidades monitorizadas y muestra distribución por tienda, precios por modelo insignia, rebajas detectadas y candidatos en zona de vigilancia (2.900–3.400 €).

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

---

## Estado actual y próximos pasos

### Fotografía del estado actual (10/11/2026)
- **Rendimiento de búsqueda**: Los 4 portales oficiales (**Bike Ocasión**, **Buhobike**, **Upway** y **Mammoth Bikes**) se rastrean en paralelo en **~51 segundos** totales (~319 e-MTBs inspeccionadas por corrida).
- **Calidad de filtrado y telemetría**: Operativos los filtros estrictos `S0` (en stock, sin reservadas) a `S6`, detección de Range Extenders incluidos, lectura de odómetros en fotos con Gemini Vision, telemetría real de batería (`SoH %` y ciclos de carga) y clasificación matemática por milímetros de recorrido de suspensión (`≤130 mm` XC > `140 mm` Trail Ligero > `150-160 mm` All-Mountain).
- **Historial de catálogo y tiempo en stock**: Tabla SQLite `historial_catalogo` registrando automáticamente la evolución diaria de precios, días en stock y rebajas acumuladas.
- **Radar de mercado CLI**: Disponible `python main.py --stats` (o `--radar`) para emitir en segundos la radiografía completa del mercado.
- **Suite de tests**: `python test_buscador.py` 100% en **GREEN**.
- **Automatización y logs**: Tarea `BuscadorBiciOcasion` activa a las 12:00 diarias con despertar automático (`WakeToRun: True`) y registro completo en `logs/buscador.log`.

### Tareas completadas en esta sesión

- [x] **TODO 1 — Historial de evolución de precios y "Tiempo en Stock" (`db.py` + `notifier.py`)**: Implementado en `historial_catalogo`, registrando cada candidata pre-filtrada con días en stock y rebajas acumuladas, formateado en las alertas de Telegram.
- [x] **TODO 2 — Clasificación objetiva de modalidad por recorrido de suspensión en milímetros (`enriquecedor_web.py` + `evaluator.py`)**: Extracción de mm de suspensión (`_extraer_recorrido`), asignación directa en `prioridad_modalidad` y descarte preventivo de modelos Enduro > 170 mm.
- [x] **TODO 3 — Modo Radar de Mercado por CLI (`python main.py --stats`)**: Comando `--stats` operativo con análisis de unidades por tienda, modelos estrella, zona de vigilancia y rebajas.
- [x] **Ejecución de búsqueda diaria en vivo**: Notificado el Top 3 a Telegram en vivo con éxito.

### Plan de trabajo propuesto para mañana (TODOs)

- [ ] **TODO 1 — Alerta proactiva en Telegram ante rebajas en la "Zona de Vigilancia" (3.000 € – 3.350 €)**
  - **Objetivo**: El radar detecta actualmente 11 bicicletas en zona de vigilancia. Si una de estas unidades recibe una rebaja que la introduce en el rango prioritario (< 3.000 €) o un descuento significativo (> 200 €), disparar una notificación prioritaria inmediata en Telegram destacando el ahorro y los días que llevaba inmovilizada en tienda.
- [ ] **TODO 2 — Extracción específica de peso en la tabla técnica de Buhobike (`#product-details dl.data-sheet`)**
  - **Objetivo**: En ciertas unidades, Buhobike declara el peso real de báscula en la pestaña "Ficha técnica" en lugar del texto del anuncio. Parsear de forma específica esta estructura para capturar el peso exacto sin recurrir al fallback del catálogo o DuckDuckGo.
- [ ] **TODO 3 — Exportación automática del Radar a Markdown (`docs/radar_mercado.md`)**
  - **Objetivo**: Generar automáticamente al final de cada ejecución diaria un reporte visual en Markdown con la evolución de precios medios por modelo insignia y tabla de oportunidades para consultarlo cómodamente desde GitHub o el IDE.

### Dependencias instaladas

- `scrapling>=0.5` (motor principal de scraping)
- `patchright>=1.64` (fork de Playwright usado por Scrapling)
- `browserforge>=1.2` (fingerprint generation)
- `msgspec>=0.22` (serialización rápida)

### Estado final

| Componente | Estado |
|------------|--------|
| Lógica de filtros, Perito Mecánico Senior, dedup, Telegram | ✅ Verificado (tests GREEN) |
| Prioridad de modalidad (XC > Light e-MTB > Trail) | ✅ Implementado (`prioridad_modalidad` en `evaluator.py` y `main.py`) |
| Desambiguación de motores BH (BH 2EXMAG vs Shimano EP801) | ✅ Verificado (BH iLynx Race/Trail fijado a 2EXMAG, iLynx+ a EP801 + batería BH) |
| Selectores Bike Ocasión | ✅ Verificados en HTML real (`h3.s_title_block a`, badge `Km / <Marca>`, 6 páginas, 180+ bicis) |
| Selectores Buhobike | ✅ Verificados en HTML real (`usar_stealth_directo=True`, `#/...-talla-m`, SKU `KM5000`, `img.thumbnail-img[alt]`) |
| Selectores Upway | ✅ Verificados en `/collections/doble-suspension` (extracción en tarjeta de año, km `\u202fkm` y talla desde `1mXX-1mYY` en ~0.8s) |
| Scraping real Upway | ✅ 23 e-MTB doble suspensión extraídas en ~0.8s (sin fetch secuencial redundante) |
| Scraping real Buhobike | ✅ 34 e-MTB extraídas en ~12s combinando trail-dobles y segunda mano, detectando candidatas < 21 kg |
| Scraping real Bike Ocasión | ✅ 182 bicis en 6 páginas con Scrapling Fetcher |
| Enriquecedor web (ficha del sitio + DuckDuckGo) | ✅ Paralelo (`ThreadPoolExecutor`), `<dt>/<dd>`, regex con `\b` y filtro anti-peso de embalaje |
| Caché de fichas de detalle | ✅ Implementado (`cache/fichas_detalle.json`, thread-safe) |
| Health check de scrapers | ✅ Implementado (alerta por log y Telegram) |
| Automatización diaria Windows 12:00 | ✅ Tarea programada `BuscadorBiciOcasion` (`main.py --once` con `WakeToRun` y `StartWhenAvailable`) |
| Logging a archivo | ✅ Implementado (`logs/buscador.log`) |
| Proxies rotatorios (ProxyRotator) | ✅ Implementado (configurable vía `PROXY_LIST`) |
| Paginación | ✅ Implementada (Bike Ocasión: 6 páginas, 180+ bicis) |
| Historial de catálogo y rebajas (`historial_catalogo`) | ✅ Implementado en SQLite (`db.py` con días en stock y cálculo de ahorro) |
| Recorrido físico de suspensión en mm | ✅ Implementado (`enriquecedor_web.py`, modelo y `prioridad_modalidad`) |
| Radar de mercado CLI (`--stats`) | ✅ Implementado (`main.py` con métricas de stock, modelos y vigilancia) |

---

## Licencia

MIT

---

## Créditos

Desarrollado como asistente de código bajo la identidad **el Gentleman** (Pi-specific coding-agent harness), siguiendo el flujo de desarrollo **Organic Driven Development (ODD)**.
