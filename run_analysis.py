"""Entrega sin interfaz: CSV auditables, gráficas PNG e informe PDF."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from analysis import Settings, analyse, validate_connections
from cleaning import prepare_data, select_scenario
from diagnostics import (critical_candidates, impact_pairs, impact_summary, microstop_assessment,
                         priority_figure, total_stops)
from reports import file_identity, technical_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/datos_hackaton.csv")
    parser.add_argument("--config", default="data/config_hackaton.csv")
    parser.add_argument("--calendar")
    parser.add_argument("--connections")
    parser.add_argument("--scenario", choices=["all", "confirmed", "provisional"], default="provisional")
    parser.add_argument("--microstop-loss-pct", type=float, default=1.0,
                        help="Umbral exploratorio de TAP en días compatibles / TR válido (porcentaje).")
    parser.add_argument("--output", default="outputs/analisis")
    args = parser.parse_args()
    settings = Settings(microstop_loss_threshold_pct=args.microstop_loss_pct)
    prepared = prepare_data(pd.read_csv(args.data), pd.read_csv(args.config),
                            calendar=pd.read_csv(args.calendar) if args.calendar else None)
    links = validate_connections(pd.read_csv(args.connections), prepared.configuration) if args.connections else None
    records, days = select_scenario(prepared, args.scenario)
    result = analyse(records, days, prepared.configuration, settings)
    candidates = critical_candidates(result.operations, records)
    pairs = impact_pairs(candidates, result.operations, records, settings, links)
    micro, micro_days = microstop_assessment(records, settings)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tables = {"indicadores": result.operations, "candidatas": candidates, "impacto_parejas": pairs,
              "impacto_resumen": impact_summary(pairs), "paradas_totales": total_stops(records),
              "microparadas_resumen": micro, "microparadas_dias": micro_days,
              "semanas": result.weekly, "calendario": days, "registros": records,
              "registros_apartados": prepared.quarantine}
    for name, frame in tables.items():
        frame.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
    for index, (line, operations) in enumerate(result.operations.groupby("Linea"), start=1):
        fig = priority_figure(operations, settings)
        if fig is not None:
            fig.savefig(output / f"prioridades_indicadores_linea_{index}.png", dpi=180)
    sources = {"Producción": file_identity(args.data), "Configuración": file_identity(args.config),
               "Calendario": file_identity(args.calendar) if args.calendar else "No aportado",
               "Conexiones": file_identity(args.connections) if args.connections else "No aportadas"}
    metadata = {"scenario": args.scenario, "settings": asdict(settings), "sources": sources,
                "figure_lines": {str(i): str(line) for i, line in enumerate(sorted(result.operations.Linea.unique()), 1)},
                "limitations": ["Coincidencia diaria no demuestra causalidad ni impacto en toda la línea.",
                                "La actividad prevista de línea no garantiza actividad prevista de cada operación.",
                                "TAP en días compatibles no es tiempo confirmado de microparadas."]}
    (output / "parametros.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "informe.pdf").write_bytes(technical_report(prepared, records, days, result, settings,
                                                        args.scenario, connections=links, source_info=sources))
    print(f"Análisis generado: {output.resolve()}")
    print(f"Candidatas: {len(candidates)}; comparaciones DES/SAT: {len(pairs)}; "
          f"paradas totales: {len(tables['paradas_totales'])}; microparadas relevantes: {int(micro.significant.sum())}")


if __name__ == "__main__":
    main()
