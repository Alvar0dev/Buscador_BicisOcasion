"""
scrapers/bike_ocasion.py
Adaptador para Bike Ocasión (bike-ocasion.com).
ADVERTENCIA: los selectores CSS son placeholders. Deben inspeccionarse en la web real
y ajustarse antes de usar en producción (S14, S11).
"""

from typing import List
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg


class BikeOcasionScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return bicis

        # TODO: reemplazar por selectores reales de bike-ocasion.com
        productos = soup.select(".product-item")  # placeholder

        for p in productos:
            try:
                titulo_el = p.select_one(".product-title")
                precio_el = p.select_one(".price")
                link_el = p.select_one("a")
                if not (titulo_el and precio_el and link_el):
                    continue

                titulo = self.limpiar_texto(titulo_el.get_text())
                precio = self._parsear_precio(precio_el.get_text())
                url = self.url_absoluta(link_el.get("href", ""))
                bici_id = self._extraer_id_url(url)

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo or "Sin título",
                    precio=precio,
                    url=url,
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[BikeOcasion] Error parseando producto: {e}")
                continue

        return bicis

    def _parsear_precio(self, texto: str) -> float:
        digitos = "".join(c for c in texto if c.isdigit() or c in ".,")
        digitos = digitos.replace(".", "").replace(",", ".")
        try:
            return float(digitos)
        except ValueError:
            return 0.0

    def _extraer_id_url(self, url: str) -> str:
        return url.split("/")[-1] or url

