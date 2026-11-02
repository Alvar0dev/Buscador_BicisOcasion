"""
main.py
Punto de entrada del buscador de bicicletas de ocasión.

Orquesta: scrape de los 4 sitios -> filtros estrictos -> nota de oportunidad
-> seleccion de la mejor oportunidad (umbral 8.5, fallback a la mejor nota)
-> base de datos (dedup) -> notificador Telegram.
Ejecucion diaria a las 12:00 con schedule + while True (S10).
"""

import schedule
import time
from datetime import datetime

from config import SITIOS, HORA_EJECUCION, NOTA_MIN_NOTIFICAR
from db import BaseDatos
from evaluator import evaluar
from notifier import enviar
from scrapers.bike_ocasion import BikeOcasionScraper
from scrapers.tuvalum import TuvalumScraper
from scrapers.buhobike import BuhobikeScraper
from scrapers.upway import UpwayScraper

# Mapa sitio -> clase scraper
SCRAPERS = {
    "Bike Ocasión": BikeOcasionScraper,
    "Tuvalum": TuvalumScraper,
    "Buhobike": BuhobikeScraper,
    "Upway": UpwayScraper,
}


def _recolectar_oportunidades(db: BaseDatos) -> list:
    """
    Recorre los 4 sitios objetivo, aplica filtros estrictos y puntuacion,
    y devuelve una lista de (bici, nota, desglose) para bicis aptas
    que aun no se hayan notificado (o que bajaron de precio).
    """
    oportunidades = []

    for sitio in SITIOS:
        clase = SCRAPERS.get(sitio.nombre)
        if clase is None:
            print(f"[main] No hay scraper implementado para {sitio.nombre}. Saltando.")
            continue

        try:
            scraper = clase(sitio)
            bicis = scraper.extraer_bicicletas()
            print(f"[{sitio.nombre}] {len(bicis)} bicicletas extraidas.")
        except Exception as e:
            print(f"[{sitio.nombre}] Error durante el scraping: {e}")
            continue

        for bici in bicis:
            apto, nota, desglose = evaluar(bici)

            if not apto:
                print(f"  DESCARTADA [{sitio.nombre}]: {bici.titulo} - {desglose}")
                continue

            if not db.debe_reenviarse(bici, nota):
                print(f"  YA ENVIADA [{sitio.nombre}] (sin bajada de precio): {bici.titulo}")
                continue

            oportunidades.append((bici, nota, desglose))

    return oportunidades


def ejecutar_busqueda() -> None:
    """Ejecuta una pasada completa de busqueda y notificacion.

    Logica de umbral (S8 actualizada):
      - Si hay bicis con nota >= NOTA_MIN_NOTIFICAR (8.5), se notifican todas.
      - Si ninguna alcanza 8.5, se notifica solo la de mejor nota de entre
        todas las paginas buscadas, para no quedar sin informar.
    """
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando busqueda de e-MTB...")
    db = BaseDatos()

    oportunidades = _recolectar_oportunidades(db)

    if not oportunidades:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
              "No se encontraron bicis aptas en ninguno de los 4 sitios.\n")
        return

    # Ordenar por nota descendente para priorizar las mejores.
    oportunidades.sort(key=lambda x: x[1], reverse=True)

    mejor_nota = oportunidades[0][1]

    # Separar las que cumplen el umbral 8.5 de las que no.
    umbral_cumplen = [o for o in oportunidades if o[1] >= NOTA_MIN_NOTIFICAR]

    if umbral_cumplen:
        a_notificar = umbral_cumplen
        print(f"[main] {len(umbral_cumplen)} bici(s) con nota >= {NOTA_MIN_NOTIFICAR}. Notificando todas.")
    else:
        a_notificar = [oportunidades[0]]
        print(f"[main] Ninguna bici alcanza {NOTA_MIN_NOTIFICAR}. "
              f"Notificando solo la mejor (nota {mejor_nota}/10): {a_notificar[0][0].titulo}")

    total_notificadas = 0
    for bici, nota, desglose in a_notificar:
        precio_anterior = db.precio_previo(bici.bici_id)
        if enviar(bici, nota, desglose):
            db.registrar(bici, nota, precio_anterior=precio_anterior)
            total_notificadas += 1
            print(f"  NOTIFICADA: {bici.titulo} - Nota {nota}/10")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
          f"{len(oportunidades)} aptas, {total_notificadas} notificadas.\n")


def main() -> None:
    """Bucle de programacion diaria a las 12:00 (S10)."""
    print(f"Buscador de e-MTB iniciado. Ejecucion diaria a las {HORA_EJECUCION}.")
    print("Presiona Ctrl+C para detener.")

    # Ejecuta una vez al iniciar (opcional; comentar si solo se quiere la hora programada)
    # ejecutar_busqueda()

    schedule.every().day.at(HORA_EJECUCION).do(ejecutar_busqueda)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
