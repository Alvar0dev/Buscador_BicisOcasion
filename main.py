"""
main.py
Punto de entrada del buscador de bicicletas de ocasión.

Orquesta: scrape de los 4 sitios -> filtros estrictos -> nota de oportunidad
-> enriquecimiento de campos faltantes (ficha del sitio + web)
-> seleccion de la mejor oportunidad (umbral 8.5, fallback a la mejor nota)
-> base de datos (dedup) -> notificador Telegram.
Ejecucion diaria a las 12:00 con schedule + while True (S10).
"""

import schedule
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config as cfg
from config import SITIOS, HORA_EJECUCION, NOTA_MIN_NOTIFICAR, NOTA_MIN_AGUARDAR
from db import BaseDatos
from evaluator import evaluar, calcular_nota_oportunidad, pasa_filtros_estrictos
from notifier import enviar
from scrapers.bike_ocasion import BikeOcasionScraper
from scrapers.buhobike import BuhobikeScraper
from scrapers.upway import UpwayScraper
from scrapers.enriquecedor_web import enriquecer_bici

# Mapa sitio -> clase scraper
SCRAPERS = {
    "Bike Ocasión": BikeOcasionScraper,
    "Buhobike": BuhobikeScraper,
    "Upway": UpwayScraper,
}

# ---------------------------------------------------------------------------
# Logging: consola + archivo logs/buscador.log
# ---------------------------------------------------------------------------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "buscador.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("buscador")


def _health_check_scrapers() -> dict:
    """
    Health check de los scrapers (tarea 10, Fase C).

    Ejecuta cada scraper y verifica que devuelva al menos 1 producto.
    Si un devuelve 0 o falla, significa que sus selectores están rotos
    (la web cambió su HTML) y se lanza una alerta por log y Telegram.

    Devuelve un dict {nombre_sitio: cantidad_productos}.
    """
    estado: dict = {}

    for sitio in SITIOS:
        clase = SCRAPERS.get(sitio.nombre)
        if clase is None:
            logger.warning(f"[Health check] No hay scraper para {sitio.nombre}.")
            estado[sitio.nombre] = 0
            continue

        try:
            scraper = clase(sitio)
            bicis = scraper.extraer_bicicletas()
            cantidad = len(bicis)
            estado[sitio.nombre] = cantidad
            if cantidad == 0:
                logger.critical(
                    f"[Health check] {sitio.nombre} devolvió 0 productos. "
                    f"POSIBLES SELECTORES ROTOS — revisar HTML de {sitio.seccion_emtb}"
                )
                _enviar_alerta_telegram(
                    f"⚠️ *Health check fallido*\n"
                    f"Sitio: {sitio.nombre}\n"
                    f"Producto: 0 bicicletas extraídas\n"
                    f"Posibles selectores rotos en {sitio.seccion_emtb}"
                )
            else:
                logger.info(f"[Health check] {sitio.nombre}: {cantidad} productos OK.")
        except Exception as e:
            logger.critical(f"[Health check] {sitio.nombre} falló: {e}")
            estado[sitio.nombre] = 0
            _enviar_alerta_telegram(
                f"⚠️ *Health check fallido*\n"
                f"Sitio: {sitio.nombre}\n"
                f"Error: {e}"
            )

    return estado


def _enviar_alerta_telegram(texto: str) -> None:
    """Envía un mensaje de alerta por Telegram si hay credenciales configuradas."""
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        logger.debug("[Alerta Telegram] Credenciales no configuradas. Se omite envío.")
        return

    import requests
    url = cfg.TELEGRAM_API_URL.format(token=cfg.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("[Alerta Telegram] Enviada.")
    except requests.RequestException as e:
        logger.error(f"[Alerta Telegram] Error enviando alerta: {e}")


def _recolectar_oportunidades(db: BaseDatos) -> list:
    """
    Recorre los 4 sitios objetivo, aplica filtros estrictos S1-S6
    (incluyendo talla M, precio 2.000-3.300 €, batería > 500 Wh, etc.)
    y calcula la nota de oportunidad a las que los pasan.

    Devuelve una lista de (bici, nota, desglose) para bicis aptas
    que aun no se hayan notificado (o que bajaron de precio).

    Se excluyen las que ya se hayan notificado (dedup salvo bajada de precio).
    """
    oportunidades = []

    for sitio in SITIOS:
        clase = SCRAPERS.get(sitio.nombre)
        if clase is None:
            logger.warning(f"No hay scraper implementado para {sitio.nombre}. Saltando.")
            continue

        try:
            scraper = clase(sitio)
            bicis = scraper.extraer_bicicletas()
            logger.info(f"[{sitio.nombre}] {len(bicis)} bicicletas extraidas.")
        except Exception as e:
            logger.error(f"[{sitio.nombre}] Error durante el scraping: {e}")
            continue

        for bici in bicis:
            # Filtros estrictos S1-S6: talla M, precio, batería, peso, modalidad.
            apto, motivo = pasa_filtros_estrictos(bici)
            if not apto:
                logger.debug(f"  DESCARTADA [{sitio.nombre}]: {bici.titulo} - {motivo}")
                continue

            # Nota de oportunidad solo para bicis que pasan filtros estrictos.
            nota, desglose = calcular_nota_oportunidad(bici)

            if not db.debe_reenviarse(bici, nota):
                logger.debug(f"  YA ENVIADA [{sitio.nombre}] (sin bajada de precio): {bici.titulo}")
                continue

            oportunidades.append((bici, nota, desglose))

    return oportunidades


def ejecutar_busqueda() -> None:
    """Ejecuta una pasada completa de busqueda y notificacion.

    Logica de umbral (S8 actualizada):
      - Se aplican filtros estrictos S1-S6 (talla M, precio 2.000-3.300 €,
        bateria > 500 Wh, etc.) a todas las bicis encontradas.
      - Si hay bicis con nota >= NOTA_MIN_NOTIFICAR (8.5), se notifican todas.
      - Si ninguna alcanza 8.5 pero hay alguna que pasa filtros estrictos,
        se notifica solo la de mejor nota (aunque este por debajo de 8.5),
        para no quedar sin informar. Nunca se notifica una bici que no
        cumpla los filtros de busqueda (por ejemplo, talla distinta a M).

    Antes de notificar, se intenta completar los campos faltantes (talla,
    bateria, km, motor, ano, peso, suspensión) usando la ficha del producto
    del propio sitio (Scrapling) y, como fallback, DuckDuckGo.
    """
    logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando busqueda de e-MTB...")

    # Health check: verificar que todos los scrapers devuelvan productos (tarea 10).
    estado_scrapers = _health_check_scrapers()
    sitios_con_problemas = [s for s, c in estado_scrapers.items() if c == 0]
    if sitios_con_problemas:
        logger.warning(
            f"[Health check] Sitios con problemas (0 productos): {', '.join(sitios_con_problemas)}. "
            f"Continuando con los que sí funcionan."
        )

    db = BaseDatos()

    oportunidades = _recolectar_oportunidades(db)

    if not oportunidades:
        logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
                    "No se encontraron bicis aptas en ninguno de los 4 sitios.\n")
        return

    # Ordenar por nota descendente para priorizar las mejores.
    oportunidades.sort(key=lambda x: x[1], reverse=True)

    mejor_nota = oportunidades[0][1]

    # Separar las que cumplen el umbral 8.5 de las que no.
    umbral_cumplen = [o for o in oportunidades if o[1] >= NOTA_MIN_NOTIFICAR]

    if umbral_cumplen:
        a_notificar = umbral_cumplen
        logger.info(f"[main] {len(umbral_cumplen)} bici(s) con nota >= {NOTA_MIN_NOTIFICAR}. Notificando todas.")
    else:
        a_notificar = [oportunidades[0]]
        logger.info(f"[main] Ninguna bici alcanza {NOTA_MIN_NOTIFICAR}. "
                    f"Notificando solo la mejor apta (nota {mejor_nota}/10): {a_notificar[0][0].titulo}")

    # Enriquecer campos faltantes en paralelo (concurrencia controlada para no saturar los sitios).
    ENRIQUECIMIENTO_WORKERS = 3
    enriquecidas = []
    with ThreadPoolExecutor(max_workers=ENRIQUECIMIENTO_WORKERS) as executor:
        futuros = {
            executor.submit(enriquecer_bici, bici, url_ficha=bici.url): (bici, nota, desglose)
            for bici, nota, desglose in a_notificar
        }
        for futuro in as_completed(futuros):
            bici_orig, nota, desglose = futuros[futuro]
            try:
                bici = futuro.result()
                logger.info(
                    f"[Enriquecido] {bici.titulo} | talla={bici.talla} bateria={bici.bateria_wh} "
                    f"km={bici.km} motor={bici.motor} ano={bici.ano} peso={bici.peso_kg} "
                    f"suspension={bici.suspension_trasera} cuadro={bici.cuadro_material} "
                    f"modalidad={bici.modalidad}"
                )
                enriquecidas.append((bici, nota, desglose))
            except Exception as e:
                logger.warning(f"[Enriquecido] Error enriqueciendo {bici_orig.titulo}: {e}")
                enriquecidas.append((bici_orig, nota, desglose))

    total_notificadas = 0
    for bici, nota, desglose in enriquecidas:
        precio_anterior = db.precio_previo(bici.bici_id)
        if enviar(bici, nota, desglose):
            db.registrar(bici, nota, precio_anterior=precio_anterior)
            total_notificadas += 1
            logger.info(f"  NOTIFICADA: {bici.titulo} - Nota {nota}/10")

    logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
                f"{len(oportunidades)} aptas, {total_notificadas} notificadas.\n")


def main() -> None:
    """Bucle de programacion diaria a las 12:00 (S10)."""
    logger.info(f"Buscador de e-MTB iniciado. Ejecucion diaria a las {HORA_EJECUCION}.")
    logger.info("Presiona Ctrl+C para detener.")

    # Ejecuta una vez al iniciar (opcional; comentar si solo se quiere la hora programada)
    # ejecutar_busqueda()

    schedule.every().day.at(HORA_EJECUCION).do(ejecutar_busqueda)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
