"""
scrapers/bicimarket.py
Adaptador para Bicimarket (bicimarket.com).
Extiende PrestaShopBaseScraper sobre la faceta de Doble Suspensión ordenada por
precio ascendente; las tallas en stock se verifican en la ficha vía enriquecedor_web.
"""

from scrapers.prestashop_base import PrestaShopBaseScraper


class BicimarketScraper(PrestaShopBaseScraper):
    PREFIJO_ID: str = "bicimarket"
    MAX_PAGINAS: int = 3
    RESPETAR_TALLA_URL: bool = False
