"""
notifier.py
Notificador de Telegram vía requests (S9).
Envía mensaje formateado en Markdown con la ficha de la bicicleta.
"""

from typing import Optional
import requests
import config as cfg


def formatear_mensaje(
    bici, nota: float, desglose: str, precio_anterior: Optional[float] = None
) -> str:
    """
    Construye el mensaje Markdown para Telegram (S9).
    Incluye: título, precio (con alerta de bajada si aplica), nota destacada 🔥,
    kilómetros, batería, cuadro, desglose de la nota y enlace directo.
    """
    km = bici.km if bici.km is not None else "no indicado"
    if getattr(bici, "range_extender_wh", None):
        extender_val = bici.range_extender_wh
        bat_interna = (bici.bateria_wh - extender_val) if bici.bateria_wh else None
        if bat_interna and bat_interna > 0:
            bateria = f"{bici.bateria_wh} Wh ({bat_interna} Wh + 🔋 {extender_val} Wh Range Extender)"
        else:
            bateria = f"{bici.bateria_wh} Wh (+ 🔋 {extender_val} Wh Range Extender)"
    elif bici.bateria_wh:
        bateria = f"{bici.bateria_wh} Wh"
    else:
        bateria = "no indicado"

    salud_pct = getattr(bici, "bateria_salud_pct", None)
    ciclos_bat = getattr(bici, "bateria_ciclos", None)
    if salud_pct is not None or ciclos_bat is not None:
        partes_soh = []
        if salud_pct is not None:
            partes_soh.append(f"SoH: {salud_pct}%")
        if ciclos_bat is not None:
            partes_soh.append(f"{ciclos_bat} ciclos")
        bateria = f"{bateria} [{' | '.join(partes_soh)}]"
    cuadro = bici.cuadro_material or "no indicado"
    motor = bici.motor or "no indicado"
    ano = bici.ano or "no indicado"
    talla = bici.talla or "no indicada"
    modalidad = bici.modalidad or "no indicada"
    garantia = (
        bici.garantia_anos
        if bici.garantia_anos is not None
        else cfg.SITIOS[0].garantia_anos
    )

    desglose_seguro = (
        str(desglose)
        .replace("_", "-")
        .replace("*", "")
        .replace("`", "'")
    )

    es_bajada = precio_anterior is not None and bici.precio < precio_anterior
    if es_bajada:
        ahorro = precio_anterior - bici.precio
        linea_precio = f"💰 Precio: *{bici.precio:.0f} €* (Antes: ~{precio_anterior:.0f} €~ | 📉 Ahorro: *-{ahorro:.0f} €*)"
        cabecera = "📉 *¡BAJADA DE PRECIO DETECTADA! Oportunidad e-MTB*"
    else:
        linea_precio = f"💰 Precio: *{bici.precio} €*"
        cabecera = "🚵‍♂️ *Nueva oportunidad de e-MTB encontrada*"

    mensaje = (
        f"{cabecera}\n\n"
        f"*{bici.titulo}*\n"
        f"🏪 Tienda: {bici.sitio}\n"
        f"{linea_precio}\n"
        f"🔥 Nota de Oportunidad: *{nota}/10*\n\n"
        f"📏 Talla: {talla}\n"
        f"⚙️ Modalidad: {modalidad}\n"
        f"⚖️ Peso: {bici.peso_kg if bici.peso_kg else 'no indicado'} kg\n"
        f"🔋 Batería: {bateria}\n"
        f"🛞 Cuadro: {cuadro}\n"
        f"⚡ Motor: {motor}\n"
        f"📅 Año: {ano}\n"
        f"🛣️ Kilómetros: {km}\n"
        f"🛡️ Garantía: {garantia} año(s)\n\n"
        f"_Valoración técnica (IA / 5 ejes):_\n{desglose_seguro}\n\n"
        f"🔗 [Enlace directo de compra]({bici.url})"
    )
    return mensaje


def enviar(bici, nota: float, desglose: str, precio_anterior: Optional[float] = None) -> bool:
    """
    Envía el mensaje a Telegram. Devuelve True si tuvo éxito.
    Maneja excepciones de red para no caer la ejecución diaria (S13).
    """
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        print("[Telegram] Credenciales no configuradas. Se omite el envío.")
        return False

    url = cfg.TELEGRAM_API_URL.format(token=cfg.TELEGRAM_BOT_TOKEN)
    texto = formatear_mensaje(bici, nota, desglose, precio_anterior=precio_anterior)
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 400:
            # Fallback sin parse_mode por si algún carácter especial rompe Markdown v1
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[Telegram] Enviado: {bici.resumen_corto()}")
        return True
    except requests.RequestException as e:
        print(f"[Telegram] Error enviando mensaje: {e}")
        return False
