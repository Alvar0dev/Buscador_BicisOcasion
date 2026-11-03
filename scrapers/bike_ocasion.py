"""
scrapers/bike_ocasion.py
Adaptador para Bike Ocasión (bike-ocasion.com).
Selectores CSS ajustados tras inspección real de la web (S14, S11).
NOTA: la URL de categoría se corrigió en config.py (sección_emtb).
"""

from typing import List, Optional
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
from scrapers.enriquecedor_web import enriquecer_bici
import config as cfg
import re


class BikeOcasionScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return bicis

        # Selectores reales observados en bike-ocasion.com (página de producto y listado)
        # Cada producto es un <article> o contenedor con título, precio y enlace
        productos = soup.select("article.ajax_block_product, article.js-product-miniature, article.product, .product-item, .product-grid-item, .product-card")

        for p in productos:
            try:
                # Título: el texto del producto está en un <a> dentro del article.
                # Evitamos el primer <a class="tm_gallery_item_box"> (imagen, texto vacío)
                # y "Añadir al carrito". Buscamos el <a> con texto significativo.
                titulo_el = None
                for a in p.select("a[href]"):
                    t = self.limpiar_texto(a.get_text())
                    if t and t.lower() != "añadir al carrito":
                        titulo_el = a
                        break

                # Precio: .price (span.price.st_discounted_price en el HTML real)
                precio_el = p.select_one(".price, .current-price, .product-price")

                # Enlace: href del mismo <a> que trae el título, o el primer <a[href]> como fallback.
                link_el = titulo_el if titulo_el else p.select_one("a[href]")

                if not (titulo_el and precio_el and link_el):
                    continue

                titulo = self.limpiar_texto(titulo_el.get_text())
                precio = self._parsear_precio(precio_el.get_text())
                url = self.url_absoluta(link_el.get("href", ""))
                bici_id = self._extraer_id_url(url)

                if not titulo or precio <= 0:
                    continue

                # Enriquecer con datos reales de la ficha de producto (solo si está en rango de precio
                # para no saturar requests; las fuera de rango se descartan por precio de todas formas).
                detalle = {}
                if cfg.PRECIO_MIN_EUR <= precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
                    detalle = self._obtener_detalle_producto(url)

                bici = Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo or "Sin título",
                    precio=precio,
                    url=url,
                    talla=detalle.get("talla"),
                    bateria_wh=detalle.get("bateria_wh"),
                    km=detalle.get("km"),
                    motor=detalle.get("motor"),
                    cuadro_material=detalle.get("cuadro_material"),
                    componentes=detalle.get("componentes"),
                    suspension_trasera=detalle.get("suspension_trasera"),
                    ano=detalle.get("ano"),
                    peso_kg=detalle.get("peso_kg"),
                    garantia_anos=self.sitio.garantia_anos,
                )

                # Enriquecimiento web automático para campos críticos faltantes
                # (peso, suspensión trasera, año) cuando el scraping de detalle no los tuvo.
                if bici.peso_kg is None or bici.suspension_trasera is None or bici.ano is None:
                    try:
                        bici = enriquecer_bici(bici)
                    except Exception as e:
                        print(f"[BikeOcasion] Enriquecedor web falló para {bici.titulo}: {e}")

                bicis.append(bici)
            except Exception as e:
                print(f"[BikeOcasion] Error parseando producto: {e}")
                continue

        return bicis

    def _obtener_detalle_producto(self, url: str) -> dict:
        """
        Entra a la ficha de producto y extrae los campos reales:
        talla, batería, kilometraje, motor, cuadro, componentes, año, peso.
        Devuelve un dict con los campos encontrados (puede estar parcialmente vacío).
        """
        detalle: dict = {}
        soup = self.sopa(url)
        if soup is None:
            return detalle

        # --- Talla ---
        talla_el = soup.select_one("article.bo-main-feature-item-size strong.bo-main-feature-value")
        if talla_el:
            talla = self.limpiar_texto(talla_el.get_text())
            # Valor ejemplo: "XL: 184cm a 193cm" -> extraer "XL"
            detalle["talla"] = talla.split(":")[0].strip() if ":" in talla else talla.split()[0]

        # --- Cuadro ---
        cuadro_el = soup.select_one("article.bo-main-feature-item-frame strong.bo-main-feature-value")
        if cuadro_el:
            detalle["cuadro_material"] = self.limpiar_texto(cuadro_el.get_text())

        # --- Batería ---
        bateria_el = soup.select_one("article.bo-main-feature-item-battery strong.bo-main-feature-value")
        if bateria_el:
            bateria = self.limpiar_texto(bateria_el.get_text())  # ej. "540Wh"
            match = re.search(r"(\d+)", bateria)
            if match:
                detalle["bateria_wh"] = int(match.group(1))

        # --- Motor ---
        motor_el = soup.select_one("article.bo-main-feature-item-motor strong.bo-main-feature-value")
        if motor_el:
            detalle["motor"] = self.limpiar_texto(motor_el.get_text())

        # --- Amortiguador (suspensión trasera -> doble suspensión) ---
        # Buscar el feature-item cuyo label sea "Amortiguador"
        for item in soup.select("article.bo-main-feature-item"):
            label_el = item.select_one("span.bo-main-feature-label")
            value_el = item.select_one("strong.bo-main-feature-value")
            if label_el and value_el:
                lbl = self.limpiar_texto(label_el.get_text())
                if lbl == "Amortiguador":
                    det = self.limpiar_texto(value_el.get_text())
                    if det and det.lower() not in ("no", "ninguno", "sin amortiguador"):
                        detalle["suspension_trasera"] = det
                    break

        # --- Cambio / componentes ---
        cambio_el = soup.select_one("article.bo-main-feature-item-transmission strong.bo-main-feature-value")
        if cambio_el:
            detalle["componentes"] = self.limpiar_texto(cambio_el.get_text())

        # --- Kilometraje ---
        # Buscar texto que contenga "Km" en la sección de features
        km_el = soup.select_one("section.product-features, div.bo-main-features-grid")
        if km_el:
            km_texto = km_el.get_text(" ", strip=True)
            match = re.search(r"(\d[\d.,]*)\s*Km\b", km_texto)
            if match:
                km_str = match.group(1).replace(".", "").replace(",", "")
                try:
                    detalle["km"] = int(km_str)
                except ValueError:
                    pass

        # --- Año: buscar en el título de la página o en meta ---
        titulo_pagina = soup.title.string if soup.title else ""
        match_ano = re.search(r"\b(20\d{2})\b", titulo_pagina)
        if match_ano:
            detalle["ano"] = int(match_ano.group(1))

        return detalle

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '3.179 €' o '3.179 € 8.000 €')."""
        # Tomar solo el primer bloque numérico antes de €
        match = re.search(r"([\d\.\s,\u00A0]+)\s*€", texto)
        if not match:
            return 0.0
        digitos = match.group(1)
        digitos = "".join(c for c in digitos if c.isdigit() or c in ".,")
        digitos = digitos.replace(".", "").replace(",", ".")
        try:
            return float(digitos)
        except ValueError:
            return 0.0

    def _extraer_id_url(self, url: str) -> str:
        """Extrae el ID numérico de la URL de producto de Bike Ocasión."""
        # URL ejemplo: /bicicletas-electricas-de-montana-doble-suspension/463682-nombre-8445881728148.html
        partes = url.rstrip("/").split("/")
        slug = partes[-1] if partes else ""
        # El ID suele ser el primer segmento numérico del slug
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
