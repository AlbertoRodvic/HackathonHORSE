"""Criterio compartido, relaciones, informes y navegación con datos sintéticos."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis import (Settings, STATUS_COLORS, analyse, map_categories, order_operations, propagation_evidence,
                      validate_connections)
from cleaning import ROW_KEYS, VALUES, prepare_data, select_scenario
from reports import operation_report, technical_report, text_color


def fixture():
    config = pd.DataFrame([["L1", "A", 1], ["L1", "B", 2], ["L1", "C", 3], ["L1", "X", 4],
                           ["L2", "A", 1]], columns=["Linea", "Operacion", "Orden_OP"])
    source = pd.DataFrame([
        ["L1", 2026, 40, 1, "A", 10, 0, 0, 12, 0, 1000],
        ["L1", 2026, 40, 1, "B", 8, 12, 1, 1, 12, 1000],
        ["L1", 2026, 40, 1, "C", 10, 0, 12, 0, 0, 1000],
        ["L1", 2026, 40, 1, "X", 10, 0, 0, 12, 0, 1000],
        ["L2", 2026, 40, 1, "A", 20, 1, 1, 0, 2, 1000],
    ], columns=ROW_KEYS + VALUES)
    prepared = prepare_data(source, config)
    records, days = select_scenario(prepared)
    settings = Settings()
    result = analyse(records, days, config, settings)
    return source, config, prepared, records, days, settings, result


class CriteriaAndReportTests(unittest.TestCase):
    def setUp(self):
        self.source, self.config, self.prepared, self.records, self.days, self.settings, self.result = fixture()

    def test_availability_boundary_and_cycle_do_not_create_old_categories(self):
        source = self.source.copy()
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP", "NPR"]] = [18, 2, 0, 0, 4, 100]
        prepared = prepare_data(source, self.config)
        records, days = select_scenario(prepared)
        row = analyse(records, days, self.config).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row.availability_pct, 90)
        self.assertGreater(row.cycle_cmin, self.settings.cycle_target_cmin)
        self.assertEqual(row["status"], "Buen funcionamiento")
        self.assertFalse(row.own_alert)
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP"]] = [17, 3]
        prepared = prepare_data(source, self.config)
        records, days = select_scenario(prepared)
        row = analyse(records, days, self.config).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row["status"], "Parada propia")

    def test_gray_reasons_share_one_map_category_and_mixed_is_color_blend(self):
        operations = pd.DataFrame({"status": ["Sin producción", "Revisar datos", "Sin datos", "Buen funcionamiento"]})
        self.assertEqual(map_categories(operations).tolist(), ["Otros", "Otros", "Otros", "Buen funcionamiento"])
        for offset in (1, 3, 5):
            des, sat, mixed = [int(STATUS_COLORS[name][offset:offset + 2], 16)
                               for name in ["Desabastecimiento", "Saturación", "Mixto"]]
            self.assertEqual(mixed, (des + sat) // 2)

    def test_induced_color_and_recurrence_share_the_same_rule(self):
        source = self.source.astype({name: float for name in ["TBF", "TAP", "DES", "SAT"]})
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP"]] = [19.36, 0, 1.76, 0.88, 0]
        p = prepare_data(source, self.config)
        r, d = select_scenario(p)
        row = analyse(r, d, self.config).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row["status"], "Desabastecimiento")
        self.assertTrue(row.des_alert)
        self.assertEqual(row.recurrence_des, 1)

    def test_both_large_induced_signals_are_mixed(self):
        source = self.source.copy()
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP"]] = [12, 0, 6, 4, 0]
        p = prepare_data(source, self.config)
        r, d = select_scenario(p)
        row = analyse(r, d, self.config).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row["status"], "Mixto")
        self.assertTrue(row.des_alert and row.sat_alert)

    def test_urgency_does_not_replace_line_order(self):
        ops = self.result.operations.loc[self.result.operations.Linea.eq("L1")]
        self.assertEqual(order_operations(ops).Operacion.tolist(), ["A", "B", "C", "X"])
        self.assertEqual(order_operations(ops, urgent=True).iloc[0].Operacion, "B")

    def test_topology_limits_compatible_effects(self):
        links = pd.DataFrame([["L1", "A", "B"], ["L1", "B", "C"]], columns=["Linea", "Origen", "Destino"])
        links = validate_connections(links, self.config)
        row = self.result.operations.loc[self.result.operations.Operacion.eq("B")].iloc[0]
        evidence = propagation_evidence(row, self.records, self.settings, links)
        self.assertEqual(set(evidence.Operacion), {"A", "C"})
        self.assertEqual(set(evidence.Distancia), {1})
        self.assertEqual(set(evidence["Señal"]), {"SAT", "DES"})

    def test_no_topology_does_not_claim_direction(self):
        row = self.result.operations.loc[self.result.operations.Operacion.eq("B")].iloc[0]
        evidence = propagation_evidence(row, self.records, self.settings)
        self.assertIn("X", evidence.Operacion.tolist())
        self.assertTrue(evidence["Hipótesis"].str.contains("confirmar").all())
        self.assertTrue(evidence.Distancia.isna().all())

    def test_unknown_connection_is_rejected(self):
        links = pd.DataFrame([["L1", "A", "MISSING"]], columns=["Linea", "Origen", "Destino"])
        with self.assertRaises(ValueError):
            validate_connections(links, self.config)

    def test_calendar_reason_is_preserved(self):
        calendar = pd.DataFrame([["L1", 2026, 40, 1, 1, "Turno especial"]],
                                columns=["Linea", "Year", "Week", "Jour", "Planned_Production", "Motivo"])
        p = prepare_data(self.source, self.config, calendar=calendar)
        self.assertEqual(p.days.loc[p.days.Linea.eq("L1"), "Motivo"].iloc[0], "Turno especial")

    def test_reports_are_real_pdfs_and_do_not_change_inputs(self):
        before = self.records.copy(deep=True)
        row = self.result.operations.loc[self.result.operations.Operacion.eq("B")].iloc[0]
        operation = operation_report(row, self.records, self.days, self.settings, "Prueba")
        general = technical_report(self.prepared, self.records, self.days, self.result, self.settings, "Prueba")
        self.assertTrue(operation.startswith(b"%PDF-"))
        self.assertTrue(general.startswith(b"%PDF-"))
        self.assertTrue(operation.rstrip().endswith(b"%%EOF"))
        self.assertGreater(len(general), 10000)
        pd.testing.assert_frame_equal(before, self.records)
        self.assertEqual(text_color("#ffffff"), "#000000")
        self.assertEqual(text_color("#000000"), "#ffffff")


class MapInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory()
        root = Path(cls.temporary.name)
        (root / "data").mkdir()
        source, config, *_ = fixture()
        source.to_csv(root / "data" / "datos_hackaton.csv", index=False)
        config.to_csv(root / "data" / "config_hackaton.csv", index=False)
        cls.script = Path("app.py").read_text(encoding="utf-8").replace(
            "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def app(self):
        app = AppTest.from_string(self.script, default_timeout=60).run()
        app.button(key="line_L1").click().run()
        self.assertFalse(app.exception)
        return app

    def test_map_is_first_and_details_require_selection(self):
        app = self.app()
        self.assertEqual(app.header[0].value, "Mapa de operaciones")
        self.assertFalse(any("Detalle" in s.value for s in app.subheader))
        buttons = [b for b in app.button if b.key and b.key.startswith("operation_")]
        self.assertEqual([b.label for b in buttons], ["A", "B", "C", "X"])
        buttons[1].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Detalle · B" == s.value for s in app.subheader))
        self.assertTrue(any(e.proto.label == "Descargar diagnóstico PDF" for e in app.get("download_button")))

    def test_filters_sort_and_grid_preserve_selection(self):
        app = self.app()
        app.selectbox(key="map_order").set_value("Urgencia").run()
        buttons = [b for b in app.button if b.key and b.key.startswith("operation_")]
        self.assertEqual(buttons[0].label, "B")
        app.multiselect(key="map_filters").set_value(["Parada propia"]).run()
        buttons = [b for b in app.button if b.key and b.key.startswith("operation_")]
        self.assertEqual([b.label for b in buttons], ["B"])
        app.button(key="toggle_map").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state["map_expanded"])
        app.multiselect(key="map_filters").set_value([]).run()
        self.assertEqual(len([b for b in app.button if b.key and b.key.startswith("operation_")]), 4)

    def test_summary_downloads_are_inside_line_cards_and_sections_are_removed(self):
        app = AppTest.from_string(self.script, default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertEqual([b.label for b in app.button], ["Ver operaciones", "Ver operaciones"])
        self.assertEqual(len(app.get("download_button")), 2)
        self.assertEqual([m.value for m in app.metric], ["1", "0"])
        self.assertFalse(any(r.label == "Sección" for r in app.radio))
        self.assertFalse(any(e.label == "Cómo interpretar los resultados" for e in app.expander))
        for block in app.get("download_button"):
            self.assertEqual(block.proto.label, "Descargar indicadores de esta línea")

    def test_analysis_menu_stays_below_map_and_line_download_is_not_repeated(self):
        app = self.app()
        menu = app.radio(key="line_analysis")
        self.assertEqual(menu.options, ["Microparadas", "Evolución", "Calendario y calidad",
                                       "Reparto de tiempos por operación", "Pérdidas propias"])
        for option in menu.options:
            app.radio(key="line_analysis").set_value(option).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.header[0].value, "Mapa de operaciones")
            self.assertFalse(any(e.proto.label == "Descargar indicadores de esta línea"
                                 for e in app.get("download_button")))
        app.button(key="back_to_lines").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.header[0].value, "Una vista de cada línea")

    def test_priority_review_shows_reasons_above_map_and_survives_filters(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            source, config, *_ = fixture()
            extra = pd.DataFrame([["L1", "D", 5], ["L1", "E", 6], ["L1", "F", 7]], columns=config.columns)
            config = pd.concat([config, extra], ignore_index=True)
            rows = pd.DataFrame([
                ["L1", 2026, 40, 1, "E", 0, 22, 0, 0, 1, 0],
                ["L1", 2026, 40, 1, "F", 20, 2, 0, 0, 1, 0],
            ], columns=source.columns)
            pd.concat([source, rows], ignore_index=True).to_csv(root / "data" / "datos_hackaton.csv", index=False)
            config.to_csv(root / "data" / "config_hackaton.csv", index=False)
            script = Path("app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(script, default_timeout=60).run()
            self.assertIn("Revisión prioritaria", [s.value for s in app.subheader])
            app.button(key="line_L1").click().run()
            self.assertFalse(app.exception)
            self.assertIn("Revisión prioritaria", [s.value for s in app.subheader])
            labels = [e.label for e in app.expander]
            for label in ["Sin producción · 1 máquinas", "Revisar datos · 1 máquinas", "Sin datos · 1 máquinas"]:
                self.assertIn(label, labels)
            self.assertIn("Otros", app.multiselect(key="map_filters").options)
            self.assertNotIn("Buen funcionamiento", app.multiselect(key="map_filters").options)
            self.assertTrue(any("Jefe de Unidad:" in m.value and "Mantenimiento:" in m.value for m in app.markdown))
            app.multiselect(key="map_filters").set_value(["Parada propia"]).run()
            self.assertFalse(app.exception)
            self.assertIn("Revisión prioritaria", [s.value for s in app.subheader])


if __name__ == "__main__":
    unittest.main()
