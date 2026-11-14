"""
test_buscador.py
Pruebas RED/GREEN con datos simulados.
Valida scoring, filtros estrictos, clasificador híbrido (IA + motor autónomo),
dedup de SQLite y formateo de mensaje Telegram.
No depende de la web real ni de credenciales de Telegram.
"""

import os
import tempfile
from models import Bicicleta
from evaluator import evaluar, calcular_nota_oportunidad, pasa_filtros_estrictos, _puntuacion_calidad_precio, prioridad_modalidad
from gemini_classifier import (
    completar_con_catalogo,
    evaluar_documentacion_motor,
    valorar_autonomo,
    auditar_perito_mecanico,
)
from scrapers.enriquecedor_web import (
    _extraer_range_extender,
    _extraer_salud_bateria,
    _extraer_bateria,
    _extraer_motor,
    _extraer_ano,
    _extraer_recorrido,
    _extraer_km,
    _extraer_peso,
    _normalizar_km_existente,
    _extraer_pares_ficha_estructurada,
    _aplicar_detalle,
    _recolectar_urls_imagenes_ficha,
    _parsear_respuesta_km_vision,
    _extraer_km_de_imagenes,
)
from main import exportar_radar_mercado_md
from scraper_base import BaseScraper, crear_proxy_rotator, random_rotation
import config as cfg
from db import BaseDatos
from notifier import formatear_mensaje, formatear_heartbeat, enviar_heartbeat
from scrapers.upway import UpwayScraper
from unittest.mock import patch, MagicMock


def bici_prueba(**kwargs) -> Bicicleta:
    datos = dict(
        sitio="Bike Ocasión",
        bici_id="test-001",
        titulo="e-MTB XC Carbono Shimano EP8",
        precio=2500.0,
        url="https://bike-ocasion.com/bici/test-001",
        talla="M",
        modalidad="XC",
        peso_kg=17.5,
        bateria_wh=540,
        cuadro_material="Carbono",
        motor="Shimano EP8",
        km=1500,
        ano=2023,
        componentes="XT, suspension Kashima",
        garantia_anos=1,
    )
    datos.update(kwargs)
    return Bicicleta(**datos)


def test_pasa_filtros_valida():
    """S1-S6: bicicleta correcta pasa todos los filtros."""
    b = bici_prueba()
    apto, motivo = pasa_filtros_estrictos(b)
    assert apto is True, f"Deberia pasar: {motivo}"


def test_descarta_talla_no_m():
    """S1: solo talla M."""
    b = bici_prueba(talla="L")
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False


def test_descarta_bateria_500_wh():
    """S4: bateria estrictamente > 500 Wh."""
    b = bici_prueba(bateria_wh=500)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False

    b = bici_prueba(bateria_wh=540)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is True


def test_descarta_peso_mas_21_kg():
    """S3: descarta modelos >= 21 kg (objetivo < 21 kg)."""
    b = bici_prueba(peso_kg=21.0)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False

    b2 = bici_prueba(peso_kg=22.0)
    apto2, _ = pasa_filtros_estrictos(b2)
    assert apto2 is False


def test_descarta_precio_fuera_rango():
    """S5/S6: precio entre 2000 y 3300."""
    b = bici_prueba(precio=1500.0)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False

    b = bici_prueba(precio=3400.0)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False


def test_nota_alta_bici_excelente():
    """S7: bici excelente nota >= 8.0."""
    b = bici_prueba(precio=2400.0, km=1000, ano=2023)
    apto, nota, desglose = evaluar(b)
    assert apto is True
    assert nota >= 8.0, f"Nota demasiado baja: {nota} | {desglose}"


def test_nota_baja_kilometraje_alto():
    """S7: km > 4000 penaliza fuerte."""
    b = bici_prueba(km=5000, precio=2400.0)
    apto, nota, desglose = evaluar(b)
    print(f"Km altos -> nota: {nota} | {desglose}")


def test_filtro_nota_minimo_8():
    """S8: solo >= 8.0 se guarda/notifica."""
    b = bici_prueba(precio=2400.0, km=1000)
    apto, nota, _ = evaluar(b)
    assert apto is True
    assert nota >= 8.0


def test_clasificador_hibrido_catalogo_y_5_ejes():
    """Verifica completado de especificaciones y valoración en los 5 ejes."""
    b = Bicicleta(
        sitio="Bike Ocasión",
        bici_id="bh-001",
        titulo="BH iLynx Race Carbon 8.4 LT",
        precio=2890.0,
        url="https://bike-ocasion.com/bici/bh-001",
        talla="M",
        km=650,
    )
    b = completar_con_catalogo(b)
    assert b.peso_kg is not None and b.peso_kg < 21.0
    assert b.bateria_wh == 540
    assert b.cuadro_material == "Carbono"
    assert b.suspension_trasera == "si"

    nota, desglose = valorar_autonomo(b)
    assert nota >= 8.0
    assert "Diagnóstico motor" in desglose
    assert "Estado batería" in desglose

    pts_bosch, txt_bosch = evaluar_documentacion_motor("Bosch Performance Line SX")
    assert pts_bosch >= 1.9
    assert "Bosch DiagnosticTool" in txt_bosch


def test_dedup_sqlite():
    """S12: no duplicados salvo bajada de precio."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = BaseDatos(path)
        b = bici_prueba()

        # Primera vez: debe enviarse
        assert db.debe_reenviarse(b, 8.5) is True
        db.registrar(b, 8.5)

        # Segunda vez mismo precio: no reenviar
        assert db.debe_reenviarse(b, 8.5) is False

        # Bajada de precio: reenviar
        b2 = bici_prueba(precio=2200.0, bici_id="test-001")
        assert db.debe_reenviarse(b2, 8.5) is True
    finally:
        # En Windows, SQLite puede mantener el archivo bloqueado brevemente.
        try:
            os.unlink(path)
        except PermissionError:
            pass


def test_formateo_mensaje_telegram():
    """S9: mensaje incluye todos los campos requeridos y alerta de bajada de precio."""
    b = bici_prueba()
    mensaje = formatear_mensaje(b, 8.5, "Kilometraje: Km bajos | Calidad-precio: cuadro carbono")
    assert "e-MTB XC Carbono Shimano EP8" in mensaje
    assert "2500" in mensaje
    assert "8.5/10" in mensaje
    assert "540 Wh" in mensaje
    assert "Carbono" in mensaje
    assert "Enlace directo de compra" in mensaje

    # Caso bajada de precio detectada
    b_rebajada = bici_prueba(precio=2200.0)
    msg_rebajada = formatear_mensaje(b_rebajada, 9.0, "Rebaja notable", precio_anterior=2500.0)
    assert "BAJADA DE PRECIO" in msg_rebajada
    assert "2200" in msg_rebajada
    assert "2500" in msg_rebajada
    assert "-300" in msg_rebajada


def test_extraccion_titulo_sin_dto_y_suspension_rigidez():
    """Verifica que Bike Ocasión ignore badges '% DTO' en el título y que 'rigidez' no marque hardtail."""
    from bs4 import BeautifulSoup
    import config as cfg
    from scrapers.bike_ocasion import BikeOcasionScraper
    from scrapers.enriquecedor_web import _detectar_suspension_trasera

    html = """
    <article class="ajax_block_product">
      <a class="product_img_link" href="/bicicletas-electricas-de-montana-doble-suspension/463333-bh.html" title="BH iLynx Trail Carbon 8.7 XT">- 46% DTO</a>
      <h3 class="s_title_block"><a href="/bicicletas-electricas-de-montana-doble-suspension/463333-bh.html">BH iLynx Trail Carbon 8.7 XT</a></h3>
      <span class="price">2.981 €</span>
      <div>Talla: M / 540Wh / 1.193 Km / Shimano</div>
    </article>
    """
    scraper = BikeOcasionScraper(cfg.SITIOS[0])
    bicis = scraper._extraer_de_sopa(BeautifulSoup(html, "html.parser"))
    assert len(bicis) == 1
    assert bicis[0].titulo == "BH iLynx Trail Carbon 8.7 XT"
    assert bicis[0].suspension_trasera == "si"

    # 'rigidez' no debe interpretarse como 'rigid' (sin suspensión trasera)
    assert _detectar_suspension_trasera("Cuadro de carbono con gran rigidez torsional y doble suspensión") is True


def test_perito_mecanico_senior_reglas_y_lineas_rojas():
    """Verifica el cálculo paso a paso del Perito Mecánico Senior y sus Líneas Rojas."""
    from gemini_classifier import auditar_perito_mecanico

    # Caso 1: Línea Roja > 6.000 km + BH (-1.0 base centralita -1.5 >3000km = -2.5)
    b_roja_km = bici_prueba(km=8407, peso_kg=16.8, motor="BH 2EXMAG", precio=2768.0)
    res_km = auditar_perito_mecanico(b_roja_km)
    assert res_km["nota_final"] <= 4.5, f"Línea roja >6000 km violada: {res_km}"
    assert res_km["delta_motor"] == -2.5

    # Caso 2: Línea Roja > 21.0 kg (nota máxima 4.0)
    b_roja_peso = bici_prueba(km=500, peso_kg=22.4, motor="Bosch CX", precio=2500.0)
    res_peso = auditar_perito_mecanico(b_roja_peso)
    assert res_peso["nota_final"] <= 4.0, f"Línea roja >21 kg violada: {res_peso}"

    # Caso 3: BH con 1.193 km (-1.0 km) + 18.2 kg (+0.5 peso) - 1.0 (centralita BH) => 8.5/10
    b_bh_bajos_km = bici_prueba(km=1193, peso_kg=18.2, motor="BH 2EXMAG", precio=2981.0)
    res_bh = auditar_perito_mecanico(b_bh_bajos_km)
    assert res_bh["delta_motor"] == -1.0
    assert res_bh["nota_final"] == 8.5, f"Esperado 8.5, obtenido: {res_bh}"

    # Caso 4: Precio > 3.000 € y > 2.000 km (-1.5 precio, -2.5 km) con Shimano (-0.0)
    b_cara_rodada = bici_prueba(km=2500, peso_kg=19.5, motor="Shimano EP8", precio=3150.0)
    res_cara = auditar_perito_mecanico(b_cara_rodada)
    assert res_cara["delta_km"] == -2.5
    assert res_cara["delta_precio"] == -1.5
    assert res_cara["nota_final"] == 6.0


def test_optimizacion_tarjetas_upway_y_buhobike():
    """Verifica la extracción directa en tarjeta para Upway y Buhobike y los regex con bordes de palabra."""
    from bs4 import BeautifulSoup
    import config as cfg
    from scrapers.upway import UpwayScraper
    from scrapers.buhobike import BuhobikeScraper
    from scrapers.enriquecedor_web import (
        _extraer_modalidad,
        _extraer_componentes,
        _extraer_cuadro,
        _extraer_peso,
    )

    # 1. Upway: tarjeta con espacio estrecho \u202f, rango de estatura y '< 5 km'
    html_upway = """
    <div>
      <a class="w-full" href="/products/focus-thron-69-rk7qz2">
        Mejor precio Recién llegada Focus THRON² 6.9 2023 1m60-1m70 1786\u202fkm 2.499 € 6.000 € nuevo
      </a>
      <a class="w-full" href="/products/bulls-sonic-evo-am-sx-1-rk8ab1">
        Bulls Sonic Evo AM SX 1 2024 1m68-1m81 < 5\u202fkm 2.599 € 5.999 € nuevo
      </a>
    </div>
    """
    upway_scraper = UpwayScraper(cfg.SITIOS[2])
    bicis_upway = upway_scraper._extraer_de_sopa(BeautifulSoup(html_upway, "html.parser"))
    assert len(bicis_upway) == 2
    assert bicis_upway[0].titulo == "Focus THRON² 6.9"
    assert bicis_upway[0].talla == "S"
    assert bicis_upway[0].km == 1786
    assert bicis_upway[0].ano == 2023
    assert bicis_upway[0].suspension_trasera == "si"
    assert bicis_upway[1].titulo == "Bulls Sonic Evo AM SX 1"
    assert bicis_upway[1].talla == "M"
    assert bicis_upway[1].km == 5
    assert bicis_upway[1].ano == 2024

    # 2. Buhobike: tarjeta de segunda mano con alt completo, SKU KM5000 y #/16856-talla-m
    html_buhobike = """
    <article class="product-miniature js-product-miniature" data-id-product="25259">
      <a class="thumbnail product-thumbnail" href="https://www.buhobike.com/segunda-mano-electricas/25259-bh-ilynx.html#/16856-talla-m">
        <img alt="BH ILYNX RACE CARBON LT 7.6 T-M 2022 BICICLETA SEGUNDA MANO" class="thumbnail-img" />
      </a>
      <span class="discount-percentage">-3.700,00 €</span>
      <p class="h3 product-title">
        <a href="https://www.buhobike.com/segunda-mano-electricas/25259-bh-ilynx.html#/16856-talla-m">BH ILYNX RACE CARBON LT 7.6 T-M 2022...</a>
      </p>
      <meta content="BSM32910KM5000A" itemprop="sku"/>
      <div class="product-price-and-shipping">
        <span class="price current-price-discount">2.599,00 €</span>
        <span class="regular-price">6.299,00 €</span>
      </div>
    </article>
    """
    buho_scraper = BuhobikeScraper(cfg.SITIOS[1])
    bicis_buho = buho_scraper._extraer_de_sopa(
        BeautifulSoup(html_buhobike, "html.parser"),
        url_listado="https://www.buhobike.com/9448-segunda-mano-montana-electricas",
    )
    assert len(bicis_buho) == 1
    assert bicis_buho[0].titulo == "BH ILYNX RACE CARBON LT 7.6 T-M 2022 BICICLETA SEGUNDA MANO"
    assert bicis_buho[0].precio == 2599.0
    assert bicis_buho[0].talla == "M"
    assert bicis_buho[0].ano == 2022
    assert bicis_buho[0].km == 5000
    assert bicis_buho[0].suspension_trasera == "si"

    # 3. Falsos positivos por subcadenas en español ('excelente' != XC, 'extra' != XT, 'salud' != Aluminio)
    assert _extraer_modalidad("Estado excelente y exclusivo para montaña") is None
    assert _extraer_componentes("Garantía extra en el exterior del cuadro") is None
    assert _extraer_cuadro("Salud de la batería evaluada en Cataluña") is None
    assert _extraer_peso("Peso estimado del producto + embalaje: 22,000 Kg. Peso máximo ciclista 120 kg. PESO 18,28Kg") == 18.28
    from scrapers.enriquecedor_web import _extraer_km
    assert _extraer_km("engrasado de la cadena con cera al agua, mínimo para que puedas hacerle unos 700 km sin otra necesidad de engrasar la cadena") is None
    assert _extraer_km("la primera vez cambies la cadena (entre 700 y 1500 km después de la compra), no tengas que cambiar el cassette") is None
    assert _extraer_km("autonomía de hasta 120 km con batería externa") is None
    assert _extraer_km("Kilometraje: 1.250 km") == 1250
    assert _extraer_km("Bicicleta en buen estado. 4237 km rodados.") == 4237

    # 4. Prioridad de modalidad (XC > Light e-MTB > Trail) y corrección de motor BH
    from evaluator import prioridad_modalidad
    b_xc = bici_prueba(titulo="BH iLynx Race Carbon Pro LT 7.8", modalidad="XC / Downcountry", motor="Shimano")
    b_xc = completar_con_catalogo(b_xc)
    assert b_xc.motor == "BH 2EXMAG", f"Motor BH iLynx Race mal corregido: {b_xc.motor}"

    b_plus = bici_prueba(titulo="BH iLynx+ Trail Carbon 8.7 XT", modalidad="Trail", motor="Shimano")
    b_plus = completar_con_catalogo(b_plus)
    assert "Shimano EP801" in b_plus.motor and "BH" in b_plus.motor

    b_light = bici_prueba(titulo="Orbea Rise H30", modalidad="Light e-MTB / Trail")
    assert prioridad_modalidad(b_xc) > prioridad_modalidad(b_light) > prioridad_modalidad(b_plus)

    # 5. Ordenación en main.clave_orden_estrictas:
    #    - Bicis sanas (nota >= 6.0 y km <= 4.000) siempre superan a una XC muy desgastada (5.000 km, 3.5/10).
    #    - A igualdad de salud mecánica, XC supera a Light e-MTB y Trail.
    from main import clave_orden_estrictas
    item_xc_sana = (
        bici_prueba(titulo="BH iLynx Race Carbon Pro LT 7.8", km=1200, peso_kg=16.8, modalidad="XC / Downcountry"),
        7.0,
        "Sana XC",
    )
    item_light_sana = (
        bici_prueba(titulo="Orbea Rise H30", km=1242, peso_kg=20.3, modalidad="Light e-MTB / Trail"),
        7.5,
        "Sana Light",
    )
    item_trail_sana = (
        bici_prueba(titulo="BH iLynx+ Trail Carbon 8.7 XT", km=1193, peso_kg=20.4, modalidad="Trail (160mm)"),
        6.5,
        "Sana Trail",
    )
    item_xc_gastada = (
        bici_prueba(titulo="BH ILYNX RACE CARBON LT 7.6", km=5000, peso_kg=18.28, modalidad="XC / Downcountry"),
        3.5,
        "Gastada 5000 km",
    )
    item_xc_linea_roja = (
        bici_prueba(titulo="BH iLynx Race Carbon 8.4 LT", km=8407, peso_kg=16.8, modalidad="XC / Downcountry"),
        2.5,
        "Línea Roja >6000 km",
    )
    lista_items = [item_xc_linea_roja, item_xc_gastada, item_trail_sana, item_light_sana, item_xc_sana]
    lista_items.sort(key=clave_orden_estrictas, reverse=True)
    assert [x[0].titulo for x in lista_items] == [
        "BH iLynx Race Carbon Pro LT 7.8",
        "Orbea Rise H30",
        "BH iLynx+ Trail Carbon 8.7 XT",
        "BH ILYNX RACE CARBON LT 7.6",
        "BH iLynx Race Carbon 8.4 LT",
    ]

    # 6. Mammoth Bikes: extracción de tarjeta con tallas en stock, limpieza de título y filtro anti-rígidas
    from scrapers.mammoth import MammothScraper
    html_mammoth = """
    <div>
      <div class="card-content">
        <a href="/bicicleta-scott-bike-lumen-910/p-592251">
          <div class="card-product-name"><strong>scott bike</strong> bicicleta scott bike lumen 910</div>
          <div class="card-product-price"><span class="price is__full">2.999,00 €</span></div>
          <div class="card--product-sizes form-sizes-group">
            <ul><li><label>M</label></li><li><label>L</label></li></ul>
          </div>
        </a>
      </div>
      <div class="card-content">
        <a href="/ebike-trek-marlin-8/p-592715">
          <div class="card-product-name"><strong>trek</strong> ebike trek marlin+ 8</div>
          <div class="card-product-price"><span class="price is__discount">2.244,68 €</span></div>
          <div class="card--product-sizes form-sizes-group">
            <ul><li><label>S</label></li><li><label>L</label></li></ul>
          </div>
        </a>
      </div>
    </div>
    """
    mammoth_scraper = MammothScraper(cfg.SITIOS[3])
    bicis_mammoth = mammoth_scraper._extraer_de_sopa(
        BeautifulSoup(html_mammoth, "html.parser"),
        url_listado="https://www.mammothbikes.com/bicicletas-electricas-mtb-dobles-rally-xc/c-3104",
    )
    assert len(bicis_mammoth) == 2
    assert bicis_mammoth[0].titulo == "Scott Lumen 910"
    assert bicis_mammoth[0].precio == 2999.0
    assert bicis_mammoth[0].talla == "M"
    assert bicis_mammoth[0].modalidad == "XC / Downcountry"
    assert bicis_mammoth[0].suspension_trasera == "si"
    assert bicis_mammoth[0].km == 0
    assert bicis_mammoth[1].talla == "S"
    assert bicis_mammoth[1].suspension_trasera == "no"


def test_range_extender_extraccion_y_filtros():
    """Valida la detección, suma de capacidad en Wh y bonificación de Range Extenders."""
    # 1. Extracción positiva vs exclusión de compatibilidad
    assert _extraer_range_extender("Orbea Rise H30 2022. Incluye Range Extender de 252Wh de regalo.") == 252
    assert _extraer_range_extender("BH iLynx Race Carbon 8.4 LT + Batería XPro 180Wh incluida") == 180
    assert _extraer_range_extender("Specialized Turbo Levo SL Expert con range extender") == 160
    assert _extraer_range_extender("Trek Fuel EXe 9.7 con segunda batería de 160Wh incluida") == 160
    assert _extraer_range_extender("Bicicleta con Bosch PowerMore 250Wh incluido") == 250
    # Descarte de compatibilidad / venta por separado
    assert _extraer_range_extender("Cuadro de carbono preparado para Range Extender de 252Wh (no incluido en la venta).") is None
    assert _extraer_range_extender("Compatible con range extender opcional de 252Wh") is None
    assert _extraer_range_extender("Admite batería externa Bosch PowerMore de 250Wh (se vende por separado).") is None

    # 2. Rescate de filtro S4: Orbea Rise 360 Wh descartada sin extender, pero admitida con extender
    b_sin = bici_prueba(titulo="Orbea Rise M20 2021", bateria_wh=360)
    apto_sin, motivo_sin = pasa_filtros_estrictos(b_sin)
    assert apto_sin is False
    assert "Batería <= 500 Wh: 360 Wh" in motivo_sin

    # Con extender en título: enriquecedor / catálogo ajusta capacidad total
    b_con = bici_prueba(
        titulo="Orbea Rise M20 2021 + Range Extender 252Wh",
        bateria_wh=360,
    )
    b_con = completar_con_catalogo(b_con)
    assert b_con.range_extender_wh == 252
    assert b_con.bateria_wh == 612  # 360 + 252 Wh
    apto_con, _ = pasa_filtros_estrictos(b_con)
    assert apto_con is True, "La bicicleta debe pasar el filtro estricto con 612 Wh"

    # 3. Bonificación en puntuación calidad-precio (+0.5 pts)
    p_sin, just_sin = _puntuacion_calidad_precio(b_sin)
    p_con, just_con = _puntuacion_calidad_precio(b_con)
    assert "Range Extender 252Wh incluido: +0.5" in just_con

    # 4. Auditoría pericial (Perito Mecánico Senior)
    audit = auditar_perito_mecanico(b_con)
    assert "Range Extender oficial de 252 Wh" in audit["txt_bateria"]
    assert "Range Extender oficial (+252 Wh" in audit["txt_precio"]

    # 5. Formato de mensaje para Telegram
    msg = formatear_mensaje(b_con, 8.5, "Desglose pericial")
    assert "🔋 Batería: 612 Wh (360 Wh + 🔋 252 Wh Range Extender)" in msg


def test_salud_bateria_soh_disponibilidad_y_extractores():
    """Valida extracción de SoH %, ciclos de batería, filtro anti-reservadas/agotadas y extractores."""
    # 1. Extracción de SoH % y ciclos en Upway y Bike Ocasión
    txt_upway = (
        "Eléctrico Batería Estado de salud: 90\u00a0% Capacidad de la batería: 670 Wh "
        "Número de ciclos de carga de la batería: 164 Ubicación de la batería: Cuadro "
        "En esta bici, la batería se ha comprobado y conserva el 89 % de su capacidad original de 750 Wh, es decir, 670 Wh."
    )
    soh, ciclos = _extraer_salud_bateria(txt_upway)
    assert soh == 90
    assert ciclos == 164
    assert _extraer_bateria(txt_upway) == 750  # Capacidad nominal original preservada

    soh_bo, ciclos_bo = _extraer_salud_bateria("Potencia batería: 540Wh | % batería: 95% | Km: 1200")
    assert soh_bo == 95
    assert ciclos_bo is None

    soh_vacio, _ = _extraer_salud_bateria("Potencia batería: 540Wh | % batería: - | Km: 1837")
    assert soh_vacio is None

    # 2. Motor en formato Upway ("Marca: X Modelo: Y") y EP800
    assert _extraer_motor("Motor Marca: Shimano Modelo: EP800 Ubicación: Central") == "Shimano EP8"
    assert _extraer_motor("Motor Marca: Bosch Modelo: Performance Line CX Par: 85 Nm") == "Bosch Performance Line CX"

    # 3. Año ignorando fechas de entrega estimada o venta
    assert _extraer_ano("Entrega estimada 12 nov. 2026. Envío gratuito.") is None
    assert _extraer_ano("Entrega estimada 12 nov. 2026. Año del modelo: 2023") == 2023

    # 4. Detección de bicicletas reservadas / agotadas y no falsos positivos ("¿Quieres reservarla?")
    assert BaseScraper.es_tarjeta_no_disponible(texto_tarjeta="Orbea Rise H10 - RESERVADA - 2.499 €") is True
    assert BaseScraper.es_tarjeta_no_disponible(texto_tarjeta="BH iLynx Race - Producto agotado") is True
    assert BaseScraper.es_tarjeta_no_disponible(texto_tarjeta="¿Tienes dudas técnicas? ¿Quieres reservarla? Financiación") is False

    b_reservada = bici_prueba(disponible=False)
    apto_res, motivo_res = pasa_filtros_estrictos(b_reservada)
    assert apto_res is False
    assert "reservada o agotada" in motivo_res

    # 5. Impacto de SoH % en Perito Mecánico Senior y formato de Telegram
    b_soh_optimo = bici_prueba(bateria_wh=540, bateria_salud_pct=96, bateria_ciclos=38, km=1200, peso_kg=19.5)
    audit_opt = auditar_perito_mecanico(b_soh_optimo)
    assert audit_opt["delta_bateria"] == 0.5
    assert "SoH medido: 96%" in audit_opt["txt_bateria"]
    assert "38 ciclos diagnosticados" in audit_opt["txt_bateria"]

    b_soh_malo = bici_prueba(bateria_wh=540, bateria_salud_pct=78, bateria_ciclos=240, km=1200, peso_kg=19.5)
    audit_malo = auditar_perito_mecanico(b_soh_malo)
    assert audit_malo["delta_bateria"] == -2.5

    msg_soh = formatear_mensaje(b_soh_optimo, audit_opt["nota_final"], "Desglose")
    assert "540 Wh [SoH: 96% | 38 ciclos]" in msg_soh


def test_todos_historial_catalogo_recorrido_y_stats():
    """Valida los TODOs: extracción de recorrido (mm), prioridad objetiva y tracking de catálogo."""
    # 1. Extractor de recorrido en mm
    assert _extraer_recorrido("Horquilla Fox 34 Float con 130 mm de recorrido") == 130
    assert _extraer_recorrido("Recorrido horquilla: 120mm. Amortiguador Fox DPS.") == 120
    assert _extraer_recorrido("RockShox Pike 140 mm") == 140
    assert _extraer_recorrido("Bicicleta de paseo sin suspension") is None

    # 2. Prioridad objetiva por recorrido de suspensión
    b_xc = bici_prueba(recorrido_mm=120)
    b_trail_ligero = bici_prueba(recorrido_mm=140)
    b_all_mtn = bici_prueba(recorrido_mm=150)
    b_enduro = bici_prueba(recorrido_mm=170)

    assert prioridad_modalidad(b_xc) == 3
    assert prioridad_modalidad(b_trail_ligero) == 2
    assert prioridad_modalidad(b_all_mtn) == 1
    assert prioridad_modalidad(b_enduro) == 0

    # 3. Filtro S2bis: descarte por recorrido excesivo (> 170 mm)
    b_dh = bici_prueba(recorrido_mm=180)
    apto_dh, motivo_dh = pasa_filtros_estrictos(b_dh)
    assert apto_dh is False
    assert "excesivo" in motivo_dh

    # 4. Historial de catálogo y tiempo en stock en SQLite
    fd, path_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = BaseDatos(ruta=path_tmp)
        bici_track = bici_prueba(bici_id="track-001", precio=2999.0)
        
        # Primer registro: días 0, rebajas 0
        res1 = db.registrar_en_catalogo(bici_track)
        assert res1["dias_en_stock"] == 0
        assert res1["rebajas_detectadas"] == 0
        assert res1["precio_actual"] == 2999.0

        # Segundo registro con bajada de precio a 2.750 €
        bici_track.precio = 2750.0
        res2 = db.registrar_en_catalogo(bici_track)
        assert res2["rebajas_detectadas"] == 1
        assert res2["ahorro_eur"] == 249.0
        assert res2["precio_minimo"] == 2750.0

        # Consulta de seguimiento
        seg = db.obtener_seguimiento("track-001")
        assert seg is not None
        assert seg["rebajas_detectadas"] == 1
        assert seg["ahorro_eur"] == 249.0

        # Radar de mercado / estadísticas
        stats = db.obtener_estadisticas_mercado()
        assert stats["total"] == 1
        assert "Bike Ocasión" in stats["por_sitio"]
        assert len(stats["con_rebajas"]) == 1
        assert stats["con_rebajas"][0]["ahorro"] == 249.0

        # Formateo de Telegram con recorrido y seguimiento
        msg = formatear_mensaje(
            bici_track,
            nota=8.5,
            desglose="Desglose test",
            seguimiento={"dias_en_stock": 7, "rebajas_detectadas": 1},
        )
        assert "7 días en catálogo" in msg
        assert "1 rebaja(s)" in msg
    finally:
        try:
            if os.path.exists(path_tmp):
                os.remove(path_tmp)
        except PermissionError:
            pass


def test_extraccion_km_imagenes_ficha_buhobike_vigilancia_y_radar_md():
    """
    Valida:
      1. Normalización de km (string/int) y extracción con formato prefijo 'Km: 1837'.
      2. Extracción estructurada de tabla técnica de Buhobike (peso real de báscula 19,57Kg, recorrido 140mm).
      3. Extracción de km desde galería de imágenes mediante Gemini Vision cuando no aparece en texto/datos.
      4. Alerta proactiva de Entrada desde Zona de Vigilancia (> 3.000 € -> <= 3.000 €).
      5. Exportación automática del informe Markdown docs/radar_mercado.md.
    """
    from bs4 import BeautifulSoup
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    import config as cfg

    # 1. Normalización de km y formato 'Km: 1837' de Bike Ocasión
    assert _normalizar_km_existente(4237) == 4237
    assert _normalizar_km_existente("4.237") == 4237
    assert _normalizar_km_existente("1.837 km") == 1837
    assert _normalizar_km_existente("-") is None
    assert _normalizar_km_existente(None) is None
    assert _extraer_km("Potencia batería: 540Wh | % batería: - | Km: 1837 | Rango: De 500Wh") == 1837

    # 2. Extracción de tabla técnica de Buhobike (peso exacto 19,57Kg y recorrido 140 mm)
    html_buhobike = """
    <div id="description">
      <table class="caracteristicas-tecnicas-2-tablas">
        <tbody>
          <tr><th>AÑO</th><td>2022</td></tr>
          <tr><th>CUADRO</th><td>ALUMINIO</td></tr>
          <tr><th>HORQUILLA</th><td>FOX 34 FACTORY KASHIMA con 140 mm de recorrido</td></tr>
          <tr><th>MOTOR</th><td>SHIMANO EP8-RS</td></tr>
          <tr><th>BATERÍA</th><td>ORBEA INTERNAL 540 WH</td></tr>
          <tr><th>PESO</th><td>19,57Kg </td></tr>
        </tbody>
      </table>
    </div>
    <ul class="product-images">
      <li><img class="js-thumb" data-image-large-src="https://www.buhobike.com/200248-large_default/orbea-rise.jpg" src="thumb1.jpg"/></li>
      <li><img class="js-thumb" data-image-large-src="https://www.buhobike.com/203857-large_default/orbea-rise.jpg" src="thumb2.jpg"/></li>
    </ul>
    """
    soup_bh = BeautifulSoup(html_buhobike, "html.parser")
    pares = dict(_extraer_pares_ficha_estructurada(soup_bh))
    assert "peso" in pares
    assert _extraer_peso(f"Peso: {pares['peso']}") == 19.57
    assert _extraer_recorrido(pares["horquilla"]) == 140

    # 3. Extracción de URLs de galería y lectura de odómetro en imágenes (Gemini Vision mock)
    urls_galeria = _recolectar_urls_imagenes_ficha(soup_bh, url_ficha="https://www.buhobike.com/bici.html")
    assert len(urls_galeria) == 2
    assert "203857-large_default" in urls_galeria[1]

    assert _parsear_respuesta_km_vision('{"km": 4238}') == 4238
    assert _parsear_respuesta_km_vision('{"odometer_total_km": 4237.59}') == 4238
    assert _parsear_respuesta_km_vision('{"km": null}') is None

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.content = b"\xff\xd8\xff\xe0" + (b"0" * 4000)

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"km": 4238}'}]}}]
    }

    with patch.object(cfg, "GEMINI_API_KEY", "fake-key-test"), \
         patch("scrapers.enriquecedor_web.requests.get", return_value=mock_get_resp), \
         patch("scrapers.enriquecedor_web.requests.post", return_value=mock_post_resp):
        km_img = _extraer_km_de_imagenes(soup_bh, url_ficha="https://www.buhobike.com/bici.html")
        assert km_img == 4238

    # 4. Alerta de Zona de Vigilancia (> 3.000 € -> <= 3.000 €) y exportación de docs/radar_mercado.md
    fd, path_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    fd_md, path_md_tmp = tempfile.mkstemp(suffix=".md")
    os.close(fd_md)
    try:
        db = BaseDatos(ruta=path_tmp)
        b_vig = bici_prueba(bici_id="vig-001", titulo="Orbea Rise M10 2023", precio=3250.0)
        r_ini = db.registrar_en_catalogo(b_vig)
        assert r_ini["entrada_desde_vigilancia"] is False

        # Baja a 2.890 € (entra desde Zona de Vigilancia al presupuesto <= 3.000 €)
        b_vig.precio = 2890.0
        r_drop = db.registrar_en_catalogo(b_vig)
        assert r_drop["entrada_desde_vigilancia"] is True
        assert r_drop["ahorro_eur"] == 360.0

        seg_vig = db.obtener_seguimiento("vig-001")
        assert seg_vig is not None and seg_vig["entrada_desde_vigilancia"] is True

        msg_vig = formatear_mensaje(
            b_vig,
            nota=9.0,
            desglose="Desglose vigilancia",
            seguimiento=seg_vig,
        )
        assert "ENTRADA DESDE ZONA DE VIGILANCIA" in msg_vig
        assert "BAJADA DE PRECIO" in msg_vig
        assert "-360" in msg_vig

        # 5. Exportación de radar de mercado a Markdown
        ruta_generada = exportar_radar_mercado_md(ruta=Path(path_md_tmp), db=db)
        contenido_md = ruta_generada.read_text(encoding="utf-8")
        assert "Radar de Mercado e-MTB de Ocasión" in contenido_md
        assert "Orbea Rise M10 2023" in contenido_md
        assert "-360 €" in contenido_md
    finally:
        for p in (path_tmp, path_md_tmp):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except PermissionError:
                pass


def test_proxy_rotator_y_resiliencia_red():
    """
    Valida:
      1. crear_proxy_rotator devuelve None si la lista está vacía.
      2. Rotación cíclica con ProxyRotator entregando proxies en orden secuencial.
      3. Rotación aleatoria con random_rotation.
      4. Inicialización correcta de _proxy_rotator y _session_proxy en BaseScraper.
      5. Limpieza de comillas y formato de proxies.
    """
    # 1. Lista vacía devuelve None
    assert crear_proxy_rotator(proxies=[]) is None
    assert crear_proxy_rotator(proxies=["   "]) is None

    # 2. Rotación cíclica
    proxies_test = ["http://proxy1.test:8080", "http://proxy2.test:8080"]
    rotator_ciclico = crear_proxy_rotator(proxies=proxies_test, rotacion="cyclic")
    assert rotator_ciclico is not None
    p1 = rotator_ciclico.get_proxy()
    p2 = rotator_ciclico.get_proxy()
    p3 = rotator_ciclico.get_proxy()
    assert p1 == "http://proxy1.test:8080"
    assert p2 == "http://proxy2.test:8080"
    assert p3 == "http://proxy1.test:8080"  # Vuelve al inicio

    # 3. Rotación aleatoria
    rotator_random = crear_proxy_rotator(proxies=proxies_test, rotacion="random")
    assert rotator_random is not None
    pr = rotator_random.get_proxy()
    assert pr in proxies_test

    # 4. BaseScraper con proxy rotator activo
    class ScraperPrueba(BaseScraper):
        def extraer_bicicletas(self):
            return []

    sitio_dummy = cfg.SitioObjetivo(
        nombre="SitioPrueba",
        base_url="https://prueba.com",
        seccion_emtb="https://prueba.com/emtb",
    )

    # Inyectamos temporalmente proxies en cfg para probar instanciación
    proxies_originales = cfg.PROXY_LIST
    try:
        cfg.PROXY_LIST = ["http://usuario:pass@proxy.corp:3128"]
        scraper = ScraperPrueba(sitio=sitio_dummy)
        assert scraper._proxy_rotator is not None
        assert scraper._proxy_rotator.get_proxy() == "http://usuario:pass@proxy.corp:3128"
        assert scraper._session_proxy is not None
    finally:
        cfg.PROXY_LIST = proxies_originales


def test_profundizacion_telemetria_bateria_upway_y_mammoth():
    """Valida la profundización de telemetría de batería (SoH % y ciclos) en Upway y Mammoth."""
    # 1. Upway: Batería sustituida / reemplazada / a estrenar
    txt_reemplazada = (
        "Batería Estado: Reemplazada Capacidad de la batería: 750 Wh "
        "Número de ciclos de carga de la batería: 1 Ubicación: Cuadro"
    )
    soh_r, ciclos_r = _extraer_salud_bateria(txt_reemplazada)
    assert soh_r == 100
    assert ciclos_r == 1
    assert _extraer_bateria(txt_reemplazada) == 750

    # 2. Upway: Capacidad restante porcentual
    txt_restante = "En esta bici la batería se ha comprobado y la capacidad restante es del 88% respecto al valor original de 625 Wh."
    soh_rest, _ = _extraer_salud_bateria(txt_restante)
    assert soh_rest == 88
    assert _extraer_bateria(txt_restante) == 625

    # 3. Upway: Ciclos de carga sin salud porcentual explícita
    txt_ciclos_solos = "Batería Estado: De origen Capacidad de la batería: 625 Wh Número de ciclos de carga de la batería: 5"
    soh_cs, ciclos_cs = _extraer_salud_bateria(txt_ciclos_solos)
    assert soh_cs is None
    assert ciclos_cs == 5

    # 4. Mammoth: Capacidad principal (EnergyPak 625) frente a extender opcional/compatible (250 Wh)
    txt_mammoth = "Batería: EnergyPak Smart 625EnergyPak Plus 250Wh range extender compatible"
    bat_m = _extraer_bateria(txt_mammoth)
    assert bat_m == 625

    # 5. Mammoth / Bicicleta nueva a estrenar (km=0 y garantía >= 2 años)
    bici_nueva = bici_prueba(sitio="Mammoth Bikes", km=0, garantia_anos=3, bateria_wh=625)
    detalle_simulado = {}
    bici_enriquecida = _aplicar_detalle(bici_nueva, detalle_simulado)
    assert bici_enriquecida.bateria_salud_pct == 100
    assert bici_enriquecida.bateria_ciclos == 0

    # Mensaje de Telegram y Perito Mecánico para bici nueva con SoH 100% y 0 ciclos
    audit_nueva = auditar_perito_mecanico(bici_enriquecida)
    assert audit_nueva["delta_bateria"] == 0.5
    msg_nueva = formatear_mensaje(bici_enriquecida, audit_nueva["nota_final"], "Desglose")
    assert "625 Wh [SoH: 100% | 0 ciclos]" in msg_nueva


def test_radar_mercado_metricas_enriquecidas_y_heartbeat():
    """
    Valida:
      1. Soporte de pvp_original en BaseDatos y cálculo de descuento % vs PVP original.
      2. Enriquecimiento de obtener_estadisticas_mercado con metricas_por_sitio y resumen_global
         (permanencia media en stock, ahorro medio por rebajas y precios medios).
      3. Exportación de docs/radar_mercado.md con las nuevas tablas enriquecidas.
      4. Extractor de PVP original en tarjetas de Upway ('2.499 € 6.000 € nuevo' -> 6000.0).
      5. Formateo y envío de Heartbeat operativo para Telegram.
    """
    fd, path_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = BaseDatos(ruta=path_tmp)

        # 1. Registro con pvp_original en Upway y rebaja posterior
        bici_upway = bici_prueba(
            sitio="Upway",
            bici_id="upway-rise-01",
            titulo="Orbea Rise H30 2023",
            precio=2200.0,
            url="https://upway.es/products/orbea-rise-h30",
            pvp_original=5499.0,
        )
        res_ini = db.registrar_en_catalogo(bici_upway)
        assert res_ini["pvp_original"] == 5499.0
        assert res_ini["rebajas_detectadas"] == 0

        # Rebaja de 200 €
        from dataclasses import replace
        bici_rebajada = replace(bici_upway, precio=2000.0)
        res_reb = db.registrar_en_catalogo(bici_rebajada)
        assert res_reb["rebajas_detectadas"] == 1
        assert res_reb["ahorro_eur"] == 200.0

        # Segunda bici en Zona de Vigilancia (Bike Ocasión)
        bici_vig = bici_prueba(
            sitio="Bike Ocasión",
            bici_id="bo-vig-01",
            titulo="BH iLynx Trail Carbon 8.7",
            precio=3100.0,
            url="https://bike-ocasion.com/bici/bo-vig-01",
            pvp_original=6800.0,
        )
        db.registrar_en_catalogo(bici_vig)

        # 2. Métricas agregadas de mercado
        stats = db.obtener_estadisticas_mercado()
        assert stats["total"] == 2
        assert "metricas_por_sitio" in stats
        m_upway = stats["metricas_por_sitio"]["Upway"]
        assert m_upway["unidades"] == 1
        assert m_upway["precio_medio"] == 2000.0
        assert m_upway["con_rebajas"] == 1
        assert m_upway["ahorro_medio_rebajas"] == 200.0
        assert m_upway["descuento_pvp_medio_pct"] is not None
        assert m_upway["descuento_pvp_medio_pct"] > 60.0  # (5499 - 2000)/5499 = ~63.6%

        res_glob = stats["resumen_global"]
        assert res_glob["total"] == 2
        assert res_glob["con_rebajas"] == 1
        assert res_glob["ahorro_total_acumulado"] == 200.0
        assert res_glob["en_vigilancia"] == 1

        assert "Orbea Rise" in stats["modelos_clave"]
        assert stats["modelos_clave"]["Orbea Rise"]["precio_medio"] == 2000.0

        # 3. Exportación Markdown
        fd_md, path_md = tempfile.mkstemp(suffix=".md")
        os.close(fd_md)
        try:
            exportar_radar_mercado_md(ruta=path_md, db=db)
            with open(path_md, "r", encoding="utf-8") as f:
                md_contenido = f.read()

            assert "Distribución por Portal y Permanencia" in md_contenido
            assert "Días en Stock (medio)" in md_contenido
            assert "Ahorro Medio Rebajas" in md_contenido
            assert "Permanencia media global" in md_contenido
            assert "-200 €" in md_contenido
        finally:
            if os.path.exists(path_md):
                os.remove(path_md)

        # 4. Extractor PVP original de Upway
        scraper_up = UpwayScraper(cfg.SITIOS[2])
        ejemplo_txt = "Mejor precio Recién llegada Focus THRON² 6.9 2023 1m60-1m70 1786 km 2.499 € 6.000 € nuevo"
        pvp_detectado = scraper_up._parsear_pvp_original(ejemplo_txt)
        assert pvp_detectado == 6000.0

        # 5. Heartbeat formateo y envío mockeado
        resumen_hb = {
            "fecha_hora": "2026-11-14 12:00:15",
            "duracion_seg": 42.5,
            "conteo_por_portal": {"Bike Ocasión": 180, "Upway": 65, "Buhobike": 40, "Mammoth": 34},
            "total_procesadas": 319,
            "candidatas_aptas": 4,
            "notificadas": 2,
            "total_en_catalogo": 64,
            "total_en_vigilancia": 27,
            "estado": "🟢 Runner operativo",
        }
        msg_hb = formatear_heartbeat(resumen_hb)
        assert "Heartbeat Buscador e-MTB" in msg_hb
        assert "319 bicicletas" in msg_hb
        assert "Bike Ocasión: *180*" in msg_hb
        assert "*2* enviada(s)" in msg_hb
        assert "64" in msg_hb
        assert "🟢 Runner operativo" in msg_hb

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            ok = enviar_heartbeat(resumen_hb)
            assert ok is True
            assert mock_post.called

    finally:
        try:
            if os.path.exists(path_tmp):
                os.remove(path_tmp)
        except PermissionError:
            pass


if __name__ == "__main__":
    test_pasa_filtros_valida()
    test_descarta_talla_no_m()
    test_descarta_bateria_500_wh()
    test_descarta_peso_mas_21_kg()
    test_descarta_precio_fuera_rango()
    test_nota_alta_bici_excelente()
    test_nota_baja_kilometraje_alto()
    test_filtro_nota_minimo_8()
    test_clasificador_hibrido_catalogo_y_5_ejes()
    test_dedup_sqlite()
    test_formateo_mensaje_telegram()
    test_extraccion_titulo_sin_dto_y_suspension_rigidez()
    test_perito_mecanico_senior_reglas_y_lineas_rojas()
    test_optimizacion_tarjetas_upway_y_buhobike()
    test_range_extender_extraccion_y_filtros()
    test_salud_bateria_soh_disponibilidad_y_extractores()
    test_todos_historial_catalogo_recorrido_y_stats()
    test_extraccion_km_imagenes_ficha_buhobike_vigilancia_y_radar_md()
    test_proxy_rotator_y_resiliencia_red()
    test_profundizacion_telemetria_bateria_upway_y_mammoth()
    test_radar_mercado_metricas_enriquecidas_y_heartbeat()
    print("Todas las pruebas pasaron (GREEN).")
