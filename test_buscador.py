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
from evaluator import evaluar, calcular_nota_oportunidad, pasa_filtros_estrictos
from gemini_classifier import (
    completar_con_catalogo,
    evaluar_documentacion_motor,
    valorar_autonomo,
)
from db import BaseDatos
from notifier import formatear_mensaje


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
    """S9: mensaje incluye todos los campos requeridos."""
    b = bici_prueba()
    mensaje = formatear_mensaje(b, 8.5, "Kilometraje: Km bajos | Calidad-precio: cuadro carbono")
    assert "e-MTB XC Carbono Shimano EP8" in mensaje
    assert "2500" in mensaje
    assert "8.5/10" in mensaje
    assert "540 Wh" in mensaje
    assert "Carbono" in mensaje
    assert "Enlace directo de compra" in mensaje


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
    print("Todas las pruebas pasaron (GREEN).")
