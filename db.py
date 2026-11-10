"""
db.py
Base de datos ligera SQLite para registrar bicicletas ya enviadas por Telegram
y mantener el historial de precios y tiempo en stock de todo el catálogo pre-filtrado.
Garantiza que no lleguen alertas duplicadas en días consecutivos, salvo que bajen de precio (S12).
"""

import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple, Dict, Any, List
import config as cfg
from models import Bicicleta


class BaseDatos:
    def __init__(self, ruta: Optional[str] = None) -> None:
        self.ruta = ruta if ruta is not None else cfg.DB_PATH
        self._crear_tabla()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ruta)
        conn.row_factory = sqlite3.Row
        return conn

    def _crear_tabla(self) -> None:
        with self._conectar() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bicis_enviadas (
                    bici_id      TEXT PRIMARY KEY,
                    sitio        TEXT NOT NULL,
                    titulo       TEXT NOT NULL,
                    precio       REAL NOT NULL,
                    url          TEXT NOT NULL,
                    nota         REAL NOT NULL,
                    fecha_envio  TEXT NOT NULL DEFAULT (datetime('now')),
                    precio_anterior REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historial_catalogo (
                    bici_id             TEXT PRIMARY KEY,
                    sitio               TEXT NOT NULL,
                    titulo              TEXT NOT NULL,
                    url                 TEXT NOT NULL,
                    precio_actual       REAL NOT NULL,
                    precio_inicial      REAL NOT NULL,
                    precio_minimo       REAL NOT NULL,
                    fecha_primera_vez   TEXT NOT NULL DEFAULT (date('now')),
                    fecha_ultima_vez    TEXT NOT NULL DEFAULT (date('now')),
                    dias_en_stock       INTEGER NOT NULL DEFAULT 0,
                    rebajas_detectadas  INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def ya_enviada(self, bici_id: str) -> bool:
        """Devuelve True si la bici ya fue notificada anteriormente."""
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT 1 FROM bicis_enviadas WHERE bici_id = ?", (bici_id,)
            ).fetchone()
        return fila is not None

    def precio_previo(self, bici_id: str) -> Optional[float]:
        """Devuelve el último precio registrado para detectar bajadas (S12)."""
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT precio FROM bicis_enviadas WHERE bici_id = ?", (bici_id,)
            ).fetchone()
        return fila["precio"] if fila else None

    def registrar(self, bici: Bicicleta, nota: float, precio_anterior: Optional[float] = None) -> None:
        """Guarda la bicicleta como enviada (S12)."""
        with self._conectar() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bicis_enviadas
                    (bici_id, sitio, titulo, precio, url, nota, precio_anterior)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bici.bici_id,
                    bici.sitio,
                    bici.titulo,
                    bici.precio,
                    bici.url,
                    nota,
                    precio_anterior,
                ),
            )
            conn.commit()

    def debe_reenviarse(self, bici: Bicicleta, nota: float) -> bool:
        """
        Decide si se debe notificar esta bicicleta.
        - Si nunca se envió: True.
        - Si ya se envió y el precio bajó: True (re-alerta por bajada de precio).
        - Si ya se envió y el precio no bajó: False (evita duplicados, S12).
        """
        if not self.ya_enviada(bici.bici_id):
            return True
        previo = self.precio_previo(bici.bici_id)
        if previo is None:
            return False
        return bici.precio < previo

    # ---------------------------------------------------------------------------
    # HISTORIAL DE CATÁLOGO Y TIEMPO EN STOCK (TODO 1)
    # ---------------------------------------------------------------------------

    def registrar_en_catalogo(self, bici: Bicicleta) -> Dict[str, Any]:
        """
        Registra o actualiza el seguimiento diario de la bicicleta en el catálogo.
        Calcula días en stock, rebajas detectadas y ahorro acumulado.
        """
        hoy_str = date.today().strftime("%Y-%m-%d")
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT * FROM historial_catalogo WHERE bici_id = ?", (bici.bici_id,)
            ).fetchone()

            if fila is None:
                # Primera vez que se detecta esta bicicleta
                conn.execute(
                    """
                    INSERT INTO historial_catalogo
                        (bici_id, sitio, titulo, url, precio_actual, precio_inicial,
                         precio_minimo, fecha_primera_vez, fecha_ultima_vez,
                         dias_en_stock, rebajas_detectadas)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                    """,
                    (
                        bici.bici_id,
                        bici.sitio,
                        bici.titulo,
                        bici.url,
                        bici.precio,
                        bici.precio,
                        bici.precio,
                        hoy_str,
                        hoy_str,
                    ),
                )
                conn.commit()
                return {
                    "dias_en_stock": 0,
                    "rebajas_detectadas": 0,
                    "precio_inicial": bici.precio,
                    "precio_minimo": bici.precio,
                    "precio_actual": bici.precio,
                    "ahorro_eur": 0.0,
                }
            else:
                precio_inicial = float(fila["precio_inicial"])
                precio_actual_prev = float(fila["precio_actual"])
                precio_minimo = min(float(fila["precio_minimo"]), bici.precio)
                rebajas = int(fila["rebajas_detectadas"])
                if bici.precio < precio_actual_prev:
                    rebajas += 1

                fecha_primera = fila["fecha_primera_vez"]
                try:
                    f_primera = datetime.strptime(fecha_primera, "%Y-%m-%d").date()
                    dias_stock = max(0, (date.today() - f_primera).days)
                except Exception:
                    dias_stock = int(fila["dias_en_stock"])

                conn.execute(
                    """
                    UPDATE historial_catalogo
                    SET precio_actual = ?,
                        precio_minimo = ?,
                        fecha_ultima_vez = ?,
                        dias_en_stock = ?,
                        rebajas_detectadas = ?
                    WHERE bici_id = ?
                    """,
                    (
                        bici.precio,
                        precio_minimo,
                        hoy_str,
                        dias_stock,
                        rebajas,
                        bici.bici_id,
                    ),
                )
                conn.commit()
                return {
                    "dias_en_stock": dias_stock,
                    "rebajas_detectadas": rebajas,
                    "precio_inicial": precio_inicial,
                    "precio_minimo": precio_minimo,
                    "precio_actual": bici.precio,
                    "ahorro_eur": max(0.0, precio_inicial - bici.precio),
                }

    def obtener_seguimiento(self, bici_id: str) -> Optional[Dict[str, Any]]:
        """Devuelve métricas de seguimiento de una bicicleta registrada."""
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT * FROM historial_catalogo WHERE bici_id = ?", (bici_id,)
            ).fetchone()
            if not fila:
                return None
            precio_inicial = float(fila["precio_inicial"])
            precio_actual = float(fila["precio_actual"])
            return {
                "dias_en_stock": int(fila["dias_en_stock"]),
                "rebajas_detectadas": int(fila["rebajas_detectadas"]),
                "precio_inicial": precio_inicial,
                "precio_minimo": float(fila["precio_minimo"]),
                "precio_actual": precio_actual,
                "ahorro_eur": max(0.0, precio_inicial - precio_actual),
                "fecha_primera_vez": fila["fecha_primera_vez"],
                "fecha_ultima_vez": fila["fecha_ultima_vez"],
            }

    def obtener_estadisticas_mercado(self) -> Dict[str, Any]:
        """
        Genera la radiografía del mercado a partir del historial de catálogo (TODO 3).
        """
        with self._conectar() as conn:
            filas = conn.execute("SELECT * FROM historial_catalogo").fetchall()

        if not filas:
            return {"total": 0, "por_sitio": {}, "modelos_clave": {}, "en_vigilancia": [], "con_rebajas": []}

        total = len(filas)
        por_sitio: Dict[str, int] = {}
        con_rebajas: List[Dict[str, Any]] = []
        en_vigilancia: List[Dict[str, Any]] = []

        familias_clave = {
            "Orbea Rise": ["orbea rise", "rise h", "rise m"],
            "BH iLynx": ["ilynx", "i-lynx"],
            "Specialized Levo SL": ["levo sl"],
            "Trek Fuel EXe": ["fuel exe"],
            "Scott Lumen": ["lumen"],
            "Mondraker Neat": ["neat"],
        }
        stats_familias: Dict[str, Dict[str, Any]] = {
            f: {"unidades": 0, "precios": [], "precio_min": None, "precio_medio": None}
            for f in familias_clave
        }

        for f in filas:
            sitio = f["sitio"]
            por_sitio[sitio] = por_sitio.get(sitio, 0) + 1
            precio = float(f["precio_actual"])
            titulo = f["titulo"].lower()

            if int(f["rebajas_detectadas"]) > 0:
                con_rebajas.append({
                    "titulo": f["titulo"],
                    "sitio": f["sitio"],
                    "precio_actual": precio,
                    "precio_inicial": float(f["precio_inicial"]),
                    "ahorro": float(f["precio_inicial"]) - precio,
                    "dias": int(f["dias_en_stock"]),
                    "url": f["url"],
                })

            if 2900.0 <= precio <= 3400.0:
                en_vigilancia.append({
                    "titulo": f["titulo"],
                    "sitio": f["sitio"],
                    "precio": precio,
                    "dias": int(f["dias_en_stock"]),
                    "url": f["url"],
                })

            for nom_fam, tokens in familias_clave.items():
                if any(t in titulo for t in tokens):
                    stats_familias[nom_fam]["unidades"] += 1
                    stats_familias[nom_fam]["precios"].append(precio)
                    break

        for nom_fam, data in stats_familias.items():
            precios = data.pop("precios")
            if precios:
                data["precio_min"] = round(min(precios), 2)
                data["precio_medio"] = round(sum(precios) / len(precios), 2)

        con_rebajas.sort(key=lambda x: x["ahorro"], reverse=True)
        en_vigilancia.sort(key=lambda x: x["precio"])

        return {
            "total": total,
            "por_sitio": por_sitio,
            "modelos_clave": {k: v for k, v in stats_familias.items() if v["unidades"] > 0},
            "con_rebajas": con_rebajas,
            "en_vigilancia": en_vigilancia,
        }
