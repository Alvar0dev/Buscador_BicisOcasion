"""
scrapers/bike_ocasion.py
Adaptador para Bike Ocasión (bike-ocasion.com).
Selectores CSS ajustados tras inspección real de la web (S14, S11).

Estrategia de extraccion:
  1. Extraer TODOS los campos visibles directamente de la tarjeta de listado
     (talla, bateria, km, motor, precio, descripcion con cuadro/suspension/componentes).
     Esto evita visitar la ficha de detalle de cada bici (que es lento y satura el sitio).
  2. Los campos que falten (peso, ano, suspensión trasera, cuadro, componentes)
     se completan después en main.py con el enriquecedor web
     (ficha del sitio + DuckDuckGo), solo para las bicis candidatas finales.
  3. Paginación: recorre múltiples páginas de la categoría para aumentar
     el volumen de bicis candidatas.
"""

from typing import List, Optional
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
from scrapers.enriquecedor_web import _extraer_range_extender
import config as cfg
import re


class BikeOcasionScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        """Extrae bicicletas de todas las páginas de la categoría (paginación)."""
        def construir_url_pagina(pagina: int) -> str:
            if pagina == 1:
                return self.sitio.seccion_emtb
            return f"{self.sitio.seccion_emtb}?page={pagina}"

        return self.extraer_bicicletas_paginado(
            construir_url_pagina=construir_url_pagina,
            max_paginas=6,
        )

    def _extraer_de_sopa(self, soup: BeautifulSoup) -> List[Bicicleta]:
        """Extrae bicicletas de un objeto BeautifulSoup ya parseado (una página)."""
        bicis: List[Bicicleta] = []

        # Selectores reales observados en bike-ocasion.com (listado)
        productos = soup.select(
            "article.ajax_block_product, article.js-product-miniature, article.product, "
            ".product-item, .product-grid-item, .product-card"
        )

        for p in productos:
            try:
                # --- Título: priorizar bloque de título h3/h2 o atributo title, evitando badges "% DTO" ---
                titulo_el = p.select_one(
                    "h3.s_title_block a, h3 a, h2 a, .product-title a, .product-name a"
                )
                if titulo_el is None:
                    for a in p.select("a[href]"):
                        t = self.limpiar_texto(a.get_text())
                        if (
                            t
                            and t.lower() != "añadir al carrito"
                            and "dto" not in t.lower()
                            and not re.match(r"^[-+\s\d%]+$", t)
                        ):
                            titulo_el = a
                            break

                # --- Precio ---
                precio_el = p.select_one(".price, .current-price, .product-price")

                # --- Enlace ---
                link_el = titulo_el if titulo_el else p.select_one("a[href]")

                if not (titulo_el and precio_el and link_el):
                    continue

                titulo = self.limpiar_texto(titulo_el.get_text())
                if not titulo or "dto" in titulo.lower():
                    titulo = self.limpiar_texto(titulo_el.get("title", ""))
                precio = self._parsear_precio(precio_el.get_text())
                url = self.url_absoluta(link_el.get("href", ""))
                bici_id = self._extraer_id_url(url)

                if not titulo or precio <= 0:
                    continue

                # --- Extraer campos de la tarjeta de listado ---
                texto_tarjeta = p.get_text(" ", strip=True)
                if self.es_tarjeta_no_disponible(p, texto_tarjeta):
                    continue
                detalle = self._extraer_de_tarjeta(texto_tarjeta)
                if detalle.get("suspension_trasera") is None:
                    url_lower = f"{url} {self.sitio.seccion_emtb}".lower()
                    if "doble-suspension" in url_lower and not any(
                        k in texto_tarjeta.lower() for k in ["rígida", "rigida", "hardtail"]
                    ):
                        detalle["suspension_trasera"] = "si"

                bici = Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo or "Sin título",
                    precio=precio,
                    url=url,
                    talla=detalle.get("talla"),
                    bateria_wh=detalle.get("bateria_wh"),
                    range_extender_wh=detalle.get("range_extender_wh"),
                    km=detalle.get("km"),
                    motor=detalle.get("motor"),
                    cuadro_material=detalle.get("cuadro_material"),
                    componentes=detalle.get("componentes"),
                    suspension_trasera=detalle.get("suspension_trasera"),
                    ano=detalle.get("ano"),
                    peso_kg=detalle.get("peso_kg"),
                    garantia_anos=self.sitio.garantia_anos,
                )

                bicis.append(bici)
            except Exception as e:
                print(f"[BikeOcasion] Error parseando producto: {e}")
                continue

        return bicis

    def _extraer_de_tarjeta(self, texto: str) -> dict:
        """
        Extrae campos directamente del texto de la tarjeta de listado de Bike Ocasión.

        Ejemplo de texto de tarjeta:
          "50% DTO Talla: M / 560Wh / 332 Km / Yamaha Giant Reign E+ 2 3.327 € 6.700 €
           Bicicleta eléctrica de doble suspensión | Cuadro de Carbono | Talla M | ..."
        """
        detalle: dict = {}
        texto_lower = texto.lower()

        # --- Talla: "Talla: M" o "Talla M" ---
        match = re.search(r"Talla\s*:\s*([A-Za-z]+)\b", texto, re.IGNORECASE)
        if match:
            detalle["talla"] = match.group(1).upper()
        else:
            match2 = re.search(r"\bTalla\s+([SMLXL]+)\b", texto, re.IGNORECASE)
            if match2:
                detalle["talla"] = match2.group(1).upper()

        # --- Batería: "560Wh", "540 Wh", etc. ---
        match = re.search(r"(\d+)\s*wh\b", texto, re.IGNORECASE)
        if match:
            try:
                detalle["bateria_wh"] = int(match.group(1))
            except ValueError:
                pass

        # --- Range Extender ---
        extender = _extraer_range_extender(texto)
        if extender:
            detalle["range_extender_wh"] = extender
            if "bateria_wh" in detalle and detalle["bateria_wh"] <= 600:
                detalle["bateria_wh"] += extender

        # --- Kilometraje: "332 Km", "1.500 Km" ---
        match = re.search(r"([\d.,]+)\s*Km\b", texto, re.IGNORECASE)
        if match:
            try:
                km_str = match.group(1).replace(".", "").replace(",", "")
                detalle["km"] = int(km_str)
            except ValueError:
                pass

        # --- Motor: extraer primero del badge "Km / <MarcaMotor>" de Bike Ocasión ---
        match_motor_badge = re.search(
            r"Km\s*/\s*(BH|Bosch|Shimano|Specialized|Yamaha|Giant|Brose|Panasonic|Fazua|TQ|Mahle|Polini|Bafang)\b",
            texto,
            re.IGNORECASE,
        )
        if match_motor_badge:
            marca_m = match_motor_badge.group(1)
            if marca_m.upper() == "BH":
                detalle["motor"] = "BH 2EXMAG"
            elif marca_m.upper() == "TQ":
                detalle["motor"] = "TQ"
            else:
                detalle["motor"] = marca_m.capitalize()
        else:
            motores_conocidos = [
                "Bosch", "Shimano EP801", "Shimano EP8", "Shimano EP6", "Yamaha", "Specialized",
                "Giant", "Brose", "Panasonic", "Fazua", "TQ", "Mahle", "BH 2EXMAG",
            ]
            for m in motores_conocidos:
                if re.search(rf"\b{re.escape(m)}\b", texto, re.IGNORECASE):
                    detalle["motor"] = m
                    break

        # Corrección técnica para modelos BH:
        # - BH iLynx Race y BH iLynx Trail (sin '+') montan SIEMPRE motor BH 2EXMAG (en ocasiones la tienda
        #   etiqueta "Shimano" por error al confundirlo con la transmisión Shimano XT/XTR).
        # - BH iLynx+ (Plus) monta Shimano EP801 con batería/sistema propietario BH.
        if re.search(r"\bbh\s+ilynx\b", texto_lower) and "ilynx+" not in texto_lower and "ilynx plus" not in texto_lower:
            detalle["motor"] = "BH 2EXMAG"
        elif "ilynx+" in texto_lower or "ilynx plus" in texto_lower:
            detalle["motor"] = "Shimano EP801 (Sistema/Batería BH)"
        elif "atomx" in texto_lower and detalle.get("motor", "").lower().startswith("shimano"):
            detalle["motor"] = "Brose S Mag"

        # --- Suspensión trasera (doble suspensión) ---
        if any(k in texto_lower for k in ["doble suspensión", "doble suspension", "full suspension", "full-suspension", "amortiguador"]):
            if not any(k in texto_lower for k in ["no tiene suspensión trasera", "sin amortiguador", "solo horquilla", "hardtail", "rigid"]):
                detalle["suspension_trasera"] = "si"

        # --- Material de cuadro ---
        if any(m in texto_lower for m in ["carbono", "carbon", "fibra de carbono"]):
            detalle["cuadro_material"] = "Carbono"
        elif any(m in texto_lower for m in ["aluminio", "aluminium", "alu"]):
            detalle["cuadro_material"] = "Aluminio"

        # --- Componentes / cambio ---
        componentes_partes = []
        if any(m in texto_lower for m in ["xt", "axs", "x0", "xtr"]):
            componentes_partes.append("XT/AXS")
        if "deore" in texto_lower:
            componentes_partes.append("Shimano Deore")
        if any(m in texto_lower for m in ["kashima", "ultimate", "factory"]):
            componentes_partes.append("Suspensión premium")
        if componentes_partes:
            detalle["componentes"] = "; ".join(dict.fromkeys(componentes_partes))

        return detalle

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '3.179 €' o '3.179 € 8.000 €')."""
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
        partes = url.rstrip("/").split("/")
        slug = partes[-1] if partes else ""
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
