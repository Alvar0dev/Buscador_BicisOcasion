"""
main.py
Punto de entrada del buscador de bicicletas de ocasión.

Orquesta: scrape de los 4 sitios -> filtros estrictos -> nota de oportunidad
-> enriquecimiento de campos faltantes (ficha del sitio + web)
-> seleccion de la mejor oportunidad (umbral 8.5, fallback a la mejor nota)
-> base de datos (dedup) -> notificador Telegram.
Ejecucion diaria a las 12:00 con schedule + while True (S10).
"""

import argparse
import schedule
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config as cfg
from config import SITIOS, HORA_EJECUCION, NOTA_MIN_NOTIFICAR, NOTA_MIN_AGUARDAR, TOP_N_NOTIFICAR
from db import BaseDatos
from evaluator import evaluar, calcular_nota_oportunidad, pasa_filtros_estrictos, prioridad_modalidad
from gemini_classifier import enriquecer_y_valorar_bici
from notifier import enviar
from scrapers.bike_ocasion import BikeOcasionScraper
from scrapers.buhobike import BuhobikeScraper
from scrapers.upway import UpwayScraper
from scrapers.mammoth import MammothScraper
from scrapers.enriquecedor_web import enriquecer_bici

# Mapa sitio -> clase scraper
SCRAPERS = {
    "Bike Ocasión": BikeOcasionScraper,
    "Buhobike": BuhobikeScraper,
    "Upway": UpwayScraper,
    "Mammoth": MammothScraper,
}

# ---------------------------------------------------------------------------
# Logging: consola + archivo logs/buscador.log
# ---------------------------------------------------------------------------
LOG_DIR = cfg.BASE_DIR / "logs"
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


def clave_orden_estrictas(item: tuple) -> tuple:
    """
    Clave de ordenación para bicicletas que superan los filtros estrictos (< 21 kg):
      1. Salud mecánica: nota >= 6.0 y km <= 4.000 (las bicis mecánicamente sanas
         siempre van antes que bicis con desgaste severo de > 4.000 km).
      2. Sin Línea Roja activa (km <= 6.000 y peso < 21.0 kg).
      3. Prioridad de modalidad: XC / Downcountry (3) > Light e-MTB (2) > Trail (1).
      4. Mayor Nota de Oportunidad del Perito Mecánico.
      5. Menor peso en kg.
    """
    bici, nota = item[0], item[1]
    km = bici.km or 0
    peso = bici.peso_kg or 20.0
    salud_mecanica = 1 if (nota >= 6.0 and km <= 4000) else 0
    sin_linea_roja = 1 if (km <= 6000 and peso < 21.0) else 0
    return (
        salud_mecanica,
        sin_linea_roja,
        prioridad_modalidad(bici),
        nota,
        -peso,
    )


def _recolectar_oportunidades(db: BaseDatos, forzar_envio: bool = False) -> list:
    """
    Recorre los sitios objetivo en una sola pasada (con health check integrado),
    pre-filtra candidatas, enriquece y valora con el clasificador híbrido
    (ficha del sitio + catálogo + Gemini Flash / motor autónomo), y aplica
    los filtros estrictos S1-S6 post-enriquecimiento.

    Devuelve una lista de (bici, nota, desglose) ordenada por relevancia:
      1. Estrictas (< 21 kg) nuevas o que bajaron de precio.
      2. Estrictas (< 21 kg) vigentes en stock (para completar Top N antes que meter >= 21 kg).
      3. Candidatas cercanas por peso nuevas.
      4. Candidatas cercanas por peso vigentes.
    """
    candidatas_pre = []

    for sitio in SITIOS:
        clase = SCRAPERS.get(sitio.nombre)
        if clase is None:
            logger.warning(f"No hay scraper implementado para {sitio.nombre}. Saltando.")
            continue

        try:
            scraper = clase(sitio)
            bicis = scraper.extraer_bicicletas()
            cantidad = len(bicis)
            if cantidad == 0:
                logger.critical(
                    f"[Health check] {sitio.nombre} devolvió 0 productos. "
                    f"POSIBLES SELECTORES ROTOS — revisar HTML de {sitio.seccion_emtb}"
                )
            else:
                logger.info(f"[{sitio.nombre}] {cantidad} bicicletas extraídas OK.")
        except Exception as e:
            logger.error(f"[{sitio.nombre}] Error durante el scraping: {e}")
            continue

        for bici in bicis:
            # Pre-filtro rápido con los campos ya conocidos de la tarjeta (precio, talla, batería...)
            apto_pre, motivo_pre = pasa_filtros_estrictos(bici)
            if not apto_pre:
                logger.debug(f"  DESCARTADA PRE [{sitio.nombre}]: {bici.titulo} - {motivo_pre}")
                continue
            candidatas_pre.append(bici)

    if not candidatas_pre:
        return []

    logger.info(f"[IA/Enriquecedor] Analizando y completando {len(candidatas_pre)} candidatas pre-filtradas...")

    estrictas_nuevas = []
    estrictas_conocidas = []
    respaldo_nuevas = []
    respaldo_conocidas = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futuros = {
            executor.submit(enriquecer_y_valorar_bici, bici): bici
            for bici in candidatas_pre
        }
        for futuro in as_completed(futuros):
            bici_orig = futuros[futuro]
            try:
                bici, nota, desglose = futuro.result()
            except Exception as e:
                logger.warning(f"[IA/Enriquecedor] Error en {bici_orig.titulo}: {e}")
                nota, desglose = calcular_nota_oportunidad(bici_orig)
                bici = bici_orig

            # Verificar Talla M, Doble Suspensión, Batería > 500 Wh y Precio 2.000-3.300 €
            if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
                continue
            if bici.bateria_wh is not None and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
                continue
            if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
                continue
            if not (cfg.PRECIO_MIN_EUR <= bici.precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR):
                continue

            es_nueva = forzar_envio or db.debe_reenviarse(bici, nota)
            apto_post, motivo_post = pasa_filtros_estrictos(bici)

            if apto_post:
                if es_nueva:
                    estrictas_nuevas.append((bici, nota, desglose))
                else:
                    estrictas_conocidas.append((bici, nota, desglose))
            else:
                logger.info(f"  [Candidata cercana] {bici.titulo}: {motivo_post} (Nota {nota}/10)")
                if es_nueva:
                    respaldo_nuevas.append((bici, nota, desglose))
                else:
                    respaldo_conocidas.append((bici, nota, desglose))

    # Ordenar las estrictas (< 21 kg) priorizando:
    #   1. Salud mecánica: nota >= 6.0 y km <= 4.000 (evita que una XC muy castigada
    #      con 5.000 km y nota 3.5/10 supere a bicis sanas de < 2.000 km con 6.5-7.5/10)
    #   2. Sin Línea Roja activa (km <= 6.000 y peso < 21.0 kg)
    #   3. Modalidad: XC / Downcountry (3) > Light e-MTB (2) > Trail (1)
    #   4. Mayor Nota de Oportunidad
    #   5. Menor peso en kg
    estrictas_nuevas.sort(key=clave_orden_estrictas, reverse=True)
    estrictas_conocidas.sort(key=clave_orden_estrictas, reverse=True)

    # Ordenar respaldo priorizando XC, menor peso y mayor nota
    clave_orden_respaldo = lambda x: (
        prioridad_modalidad(x[0]),
        -(x[0].peso_kg or 25.0),
        x[1],
    )
    respaldo_nuevas.sort(key=clave_orden_respaldo, reverse=True)
    respaldo_conocidas.sort(key=clave_orden_respaldo, reverse=True)

    seleccion = list(estrictas_nuevas)
    for pool in (estrictas_conocidas, respaldo_nuevas, respaldo_conocidas):
        if len(seleccion) >= TOP_N_NOTIFICAR:
            break
        faltantes = TOP_N_NOTIFICAR - len(seleccion)
        seleccion.extend(pool[:faltantes])

    return seleccion


def ejecutar_busqueda(forzar_envio: bool = False) -> None:
    """Ejecuta una pasada completa de búsqueda, clasificación IA y notificación Top N."""
    logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando búsqueda de e-MTB...")

    db = BaseDatos()
    oportunidades = _recolectar_oportunidades(db, forzar_envio=forzar_envio)

    if not oportunidades:
        logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
                    "No se encontraron bicis aptas en ninguno de los sitios.\n")
        return

    # Seleccionar el Top N (por defecto las 3 más interesantes)
    a_notificar = oportunidades[:TOP_N_NOTIFICAR]
    mejor_nota = max(x[1] for x in a_notificar)
    logger.info(
        f"[main] Seleccionadas las {len(a_notificar)} bicicletas más interesantes "
        f"(mejor nota: {mejor_nota}/10)."
    )

    total_notificadas = 0
    for bici, nota, desglose in a_notificar:
        precio_anterior = db.precio_previo(bici.bici_id)
        if enviar(bici, nota, desglose, precio_anterior=precio_anterior):
            db.registrar(bici, nota, precio_anterior=precio_anterior)
            total_notificadas += 1
            logger.info(f"  NOTIFICADA: {bici.titulo} ({bici.peso_kg} kg) - Nota {nota}/10")

    logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
                f"{len(oportunidades)} candidatas aptas, {total_notificadas} notificadas.\n")


def main() -> None:
    """Punto de entrada CLI: soporta ejecución única (--once) o bucle diario a las 12:00 (S10)."""
    parser = argparse.ArgumentParser(description="Buscador de e-MTB de Ocasión")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta una sola búsqueda inmediatamente y termina (ideal para Task Scheduler).",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Fuerza el envío del Top 3 aunque ya figuren en bicis_enviadas.db.",
    )
    args = parser.parse_args()

    if args.once:
        ejecutar_busqueda(forzar_envio=args.forzar)
        return

    logger.info(f"Buscador de e-MTB iniciado. Ejecucion diaria a las {HORA_EJECUCION}.")
    logger.info("Presiona Ctrl+C para detener.")

    ejecutar_busqueda(forzar_envio=args.forzar)
    schedule.every().day.at(HORA_EJECUCION).do(ejecutar_busqueda)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
