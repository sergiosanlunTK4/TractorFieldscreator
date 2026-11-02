"""Pruebas del CLI: omisión limpia de archivos sin puntos en México."""
from __future__ import annotations

import sys

import pandas as pd

from campos_tractor.cli import main


def test_cli_omite_archivo_fuera_de_mexico(tmp_path, monkeypatch, capsys):
    datos = tmp_path / 'datos'
    datos.mkdir()
    pd.DataFrame([{
        'timestamp': '2026-06-01T08:00:00Z',
        'lat': 0.0,
        'lon': 0.0,
        'machine_id': 'maquina_sintetica',
    }]).to_csv(datos / 'fuera.csv', index=False)
    salida = tmp_path / 'salida'
    monkeypatch.setattr(sys, 'argv', [
        'campos-tractor', '--datos', str(datos), '--salida', str(salida),
        '--sin-cache', '--sin-qgz'])
    assert main() == 1
    assert 'No hay puntos dentro de México' in capsys.readouterr().out
