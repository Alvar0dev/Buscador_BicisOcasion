"""
notifier.py
Notificador de Telegram vía requests (S9).
Envía mensaje formateado en Markdown con la ficha de la bicicleta.
"""

import requests
import config as cfg


def formatear_mensaje(bici, nota: float, desglose: str) -> str:
    """
    Construye el mensaje Markdown para Telegram (S9).
    Incluye: título, precio, nota destacada 🔥, kilómetros, batería, cuadro,
    desglose de la nota y enlace directo.
    """
    km = bici.km if bici.km is not None else "no indicado"
    bateria = f"{bici.bateria_wh} Wh" if bici.bateria_wh else "no indicado"
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

    mensaje = (
        f"🚵‍♂️ *Nueva oportunidad de e-MTB encontrada*\n\n"
        f"*{bici.titulo}*\n"
        f"🏪 Tienda: {bici.sitio}\n"
        f"💰 Precio: *{bici.precio} €*\n"
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
        f"_Desglose de la nota:_\n{desglose}\n\n"
        f"🔗 [Enlace directo de compra]({bici.url})"
    )
    return mensaje


def enviar(bici, nota: float, desglose: str) -> bool:
    """
    Envía el mensaje a Telegram. Devuelve True si tuvo éxito.
    Maneja excepciones de red para no caer la ejecución diaria (S13).
    """
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        print("[Telegram] Credenciales no configuradas. Se omite el envío.")
        return False

    url = cfg.TELEGRAM_API_URL.format(token=cfg.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": formatear_mensaje(bici, nota, desglose),
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[Telegram] Enviado: {bici.resumen_corto()}")
        return True
    except requests.RequestException as e:
        print(f"[Telegram] Error enviando mensaje: {e}")
        return False
