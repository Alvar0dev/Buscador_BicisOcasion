"""
main.py
Punto de entrada del buscador de bicicletas de ocasión.

Orquesta: scrape de los 4 sitios -> filtros estrictos -> nota de oportunidad
-> base de datos (dedup) -> notificador Telegram.
Ejecucion diaria a las 12:00 con schedule + while True (S10).
"""

import schedule
import time
from datetime import datetime

from config import SITIOS, HORA_EJECUCION
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


def ejecutar_busqueda() -> None:
    """Ejecuta una pasada completa de busqueda y notificacion."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando busqueda de e-MTB...")
    db = BaseDatos()
    total_encontradas = 0
    total_notificadas = 0

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
            total_encontradas += 1
            apto, nota, desglose = evaluar(bici)

            if not apto:
                print(f"  DESCARTADA: {bici.titulo} - {desglose}")
                continue

            if not db.debe_reenviarse(bici, nota):
                print(f"  YA ENVIADA (sin bajada de precio): {bici.titulo}")
                continue

            precio_anterior = db.precio_previo(bici.bici_id)
            if enviar(bici, nota, desglose):
                db.registrar(bici, nota, precio_anterior=precio_anterior)
                total_notificadas += 1
                print(f"  NOTIFICADA: {bici.titulo} - Nota {nota}/10")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado. "
          f"{total_encontradas} encontradas, {total_notificadas} notificadas.\n")


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
