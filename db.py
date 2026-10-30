"""
db.py
Base de datos ligera SQLite para registrar bicicletas ya enviadas por Telegram.
Garantiza que no lleguen alertas duplicadas en días consecutivos, salvo que bajen de precio (S12).
"""

import sqlite3
from typing import Optional, Tuple
from models import Bicicleta


class BaseDatos:
    def __init__(self, ruta: str = "bicis_enviadas.db") -> None:
        self.ruta = ruta
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
