"""
scrapers/fabregues.py
Adaptador para Fabregues Bicicletas (fabreguesbicicletas.com).
Extiende PrestaShopBaseScraper limpia SKU BH '|EC796|' en títulos, respeta unidades
'TEST RIDE' (km=None) y delega verificación real de talla M/MD a la ficha de producto.
"""

import re
from typing import Optional, Tuple
from scrapers.prestashop_base import PrestaShopBaseScraper


class FabreguesScraper(PrestaShopBaseScraper):
    PREFIJO_ID: str = "fabregues"
    MAX_PAGINAS: int = 4
    RESPETAR_TALLA_URL: bool = False

    def _extraer_titulo_y_url(self, card) -> Tuple[Optional[str], str]:
        titulo, href = super()._extraer_titulo_y_url(card)
        if titulo:
            titulo = re.sub(r"\s*\|[A-Z0-9\-]+\|\s*$", "", titulo).strip()
        return titulo, href
