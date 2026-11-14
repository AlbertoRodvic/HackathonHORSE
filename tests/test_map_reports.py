"""Criterio compartido, relaciones, informes y navegación con datos sintéticos."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from analysis import (Settings, STATUS_COLORS, analyse, map_categories, order_operations, order_time_operations, signal_conditions, propagation_evidence,
                      validate_connections)
from cleaning import ROW_KEYS, VALUES, prepare_data, select_scenario
from reports import operation_report, technical_report, classification_report, text_color


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

    def test_color_is_largest_loss_and_mixed_only_means_close_des_sat(self):
        frame = pd.DataFrame({"TBF_pct": [90, 80, 80, 80, 80, 80, 80],
                              "TAP": [10, 12, 1, 1, 1, 0, 8],
                              "DES": [0, 5, 12, 6, 8, 12, 8],
                              "SAT": [0, 3, 7, 13, 11, 8, 4]})
        own, des, sat = signal_conditions(frame, Settings())
        self.assertEqual(list(zip(own, des, sat)), [
            (False, False, False), (True, False, False), (False, True, False),
            (False, False, True), (False, True, True), (False, True, False), (True, False, False)])

    def test_runtime_order_matches_percentage_bars_not_absolute_hours(self):
        ops = self.result.operations.iloc[:2].copy()
        ops["Operacion"] = ["A", "B"]
        ops["TBF"] = [8, 70]
        ops["TR"] = [10, 100]
        ops["TBF_pct"] = [80, 70]
        self.assertEqual(order_time_operations(ops, by_runtime=True).Operacion.tolist(), ["B", "A"])

    def test_legend_groups_all_acceptable_operations_in_green(self):
        from reports import _legend
        names = [name for name, _ in _legend(Settings())]
        self.assertNotIn("Mixto", names)
        self.assertNotIn("Elemento lento", names)
        self.assertIn("Funcionamiento aceptable", names)
        self.assertEqual(STATUS_COLORS["Elemento lento"], STATUS_COLORS["Funcionamiento aceptable"])
        self.assertEqual(STATUS_COLORS["Buen funcionamiento"], STATUS_COLORS["Funcionamiento aceptable"])

    def test_urgency_groups_colors_then_runtime_and_keeps_green_subtypes_together(self):
        statuses = ["Parada propia", "Saturación", "Desabastecimiento", "Mixto", "Buen funcionamiento", "Elemento lento", "Sin datos",
                    "Parada propia", "Buen funcionamiento", "Revisar datos", "Sin producción"]
        operations = pd.concat([self.result.operations.iloc[[0]]] * len(statuses), ignore_index=True)
        operations["status"] = statuses
        operations["Operacion"] = [f"OP{index}" for index in range(len(statuses))]
        operations["Orden_OP"] = list(range(len(statuses)))
        operations["TBF_pct"] = [70, 60, 80, 50, 95, 90, float("nan"), 45, 92, 0, 0]
        ordered = order_operations(operations.iloc[::-1], urgent=True)
        self.assertEqual(ordered.Operacion.tolist(), ["OP7", "OP0", "OP1", "OP2", "OP3", "OP5", "OP8", "OP4", "OP10", "OP9", "OP6"])

    def test_runtime_threshold_gates_all_stop_types_and_weekly_signals(self):
        cases = [(90, 10, 0, 0, "Buen funcionamiento"),
                 (90, 0, 10, 0, "Buen funcionamiento"),
                 (90, 0, 0, 10, "Buen funcionamiento"),
                 (89, 11, 0, 0, "Parada propia"),
                 (89, 0, 11, 0, "Desabastecimiento"),
                 (89, 0, 0, 11, "Saturación"),
                 (80, 10, 10, 0, "Parada propia")]
        for tbf, tap, des, sat, expected in cases:
            with self.subTest(times=(tbf, tap, des, sat)):
                source = self.source.copy()
                source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP", "NPR"]] = [tbf, tap, des, sat, int(tap > 0), 10000]
                prepared = prepare_data(source, self.config)
                records, days = select_scenario(prepared)
                result = analyse(records, days, self.config)
                row = result.operations.loc[result.operations.Linea.eq("L2")].iloc[0]
                self.assertEqual(row["status"], expected)
                weekly = result.weekly.loc[result.weekly.Linea.eq("L2")].iloc[0]
                self.assertEqual(weekly["status"], expected)
                if tbf == 90:
                    self.assertFalse(row[["own_alert", "des_alert", "sat_alert"]].any())
                    self.assertEqual(row.recurrence_own + row.recurrence_des + row.recurrence_sat, 0)

    def test_cycle_splits_no_alerts_without_overriding_stop_signals(self):
        source = self.source.copy()
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP", "NPR"]] = [18, 2, 0, 0, 4, 100]
        prepared = prepare_data(source, self.config)
        records, days = select_scenario(prepared)
        row = analyse(records, days, self.config).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row.availability_pct, 90)
        self.assertGreater(row.cycle_cmin, self.settings.cycle_target_cmin)
        self.assertEqual(row["status"], "Elemento lento")
        self.assertFalse(row.own_alert)
        row = analyse(records, days, self.config, Settings(cycle_target_cmin=1080)).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row["status"], "Buen funcionamiento")
        row = analyse(records, days, self.config, Settings(availability_target=95)).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row["status"], "Parada propia")
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP"]] = [17, 3]
        prepared = prepare_data(source, self.config)
        records, days = select_scenario(prepared)
        row = analyse(records, days, self.config).operations.loc[lambda f: f.Linea.eq("L2")].iloc[0]
        self.assertEqual(row["status"], "Parada propia")

    def test_gray_reasons_share_one_map_category(self):
        operations = pd.DataFrame({"status": ["Sin producción", "Revisar datos", "Sin datos", "Buen funcionamiento"]})
        self.assertEqual(map_categories(operations).tolist(), ["Otros", "Otros", "Otros", "Funcionamiento aceptable"])

    def test_classification_pdf_uses_scope_and_current_thresholds(self):
        from unittest.mock import patch
        import reports
        captured = []
        build_pdf = reports._build

        def capture(story, title):
            captured.extend(item.getPlainText() for item in story if hasattr(item, "getPlainText"))
            return build_pdf(story, title)

        with patch("reports._build", side_effect=capture):
            pdf = classification_report(Settings(availability_target=95, cycle_target_cmin=120), "L1", [(2026, 40)], "Todos")
        self.assertTrue(pdf.startswith(b"%PDF"))
        text = " ".join(captured)
        for value in ["L1", "2026-S40", "95%", "120", "elementos lentos", "Mixto"]:
            self.assertIn(value, text)

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
        source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP"]] = [12, 0, 5, 4, 0]
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
        from unittest.mock import patch
        import reports
        before = self.records.copy(deep=True)
        row = self.result.operations.loc[self.result.operations.Operacion.eq("B")].iloc[0]
        captured = []
        build_pdf = reports._build

        def capture(story, title):
            captured.extend(item.getPlainText() for item in story if hasattr(item, "getPlainText"))
            return build_pdf(story, title)

        with patch("reports._build", side_effect=capture):
            operation = operation_report(row, self.records, self.days, self.settings, "Prueba")
        for heading in ["Por qué tiene este color", "Registros seleccionados y trazabilidad", "Balance horario de los registros diarios"]:
            self.assertIn(heading, captured)
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
        self.assertFalse(any(e.label == "Por qué tiene este color" for e in app.expander))
        self.assertNotIn("Registros diarios de la operación seleccionada", [s.value for s in app.subheader])

    def test_problematic_chart_filters_and_draws_own_availability(self):
        from unittest.mock import patch
        from diagnostics import investigation_figure
        app = self.app()
        captured = []

        def capture(operations, settings, metric="availability_pct"):
            captured.append((operations.copy(), metric))
            return investigation_figure(operations, settings, metric=metric)

        with patch("diagnostics.investigation_figure", side_effect=capture):
            app.radio(key="line_analysis").set_value("Máquinas más problemáticas").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(captured), 1)
        operations, metric = captured[0]
        # A, C y X están bajo el 90 % de TBF/TR, pero tienen Dp=100 %: no deben entrar.
        self.assertEqual(operations.Operacion.tolist(), ["B"])
        self.assertEqual(metric, "availability_pct")
        self.assertTrue(operations.availability_pct.lt(90).all())
        self.assertIn("Máquinas con disponibilidad propia < 90% · 1", [s.value for s in app.subheader])

    def test_effect_filter_keeps_only_the_selected_signal(self):
        app = self.app()
        next(b for b in app.button if b.key and b.key.startswith("operation_") and b.label == "B").click().run()

        def evidence():
            panel = next(e for e in app.expander if e.label == "Posibles efectos sobre otras operaciones y fuentes de espera")
            return panel.dataframe[0].value

        self.assertEqual(set(evidence()["Señal"]), {"DES", "SAT"})
        self.assertNotIn("Distancia", evidence().columns)
        self.assertFalse(evidence()["Hipótesis"].str.contains("conexión por confirmar").any())
        app.selectbox(key="operation_effect").set_value("Desabastecimiento en otras operaciones (DES)").run()
        self.assertFalse(app.exception)
        self.assertEqual(set(evidence()["Señal"]), {"DES"})
        app.selectbox(key="operation_effect").set_value("Saturación en otras operaciones (SAT)").run()
        self.assertEqual(set(evidence()["Señal"]), {"SAT"})
        app.selectbox(key="operation_effect").set_value("Fuentes de espera de la seleccionada (TAP)").run()
        self.assertTrue(evidence().empty)
        app.selectbox(key="operation_effect").set_value("Todos").run()
        self.assertEqual(set(evidence()["Señal"]), {"DES", "SAT"})

    def test_map_has_no_balance_filter_and_preserves_source_records(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            source, config, *_ = fixture()
            source.loc[source.Linea.eq("L1") & source.Operacion.eq("A"), "TBF"] = 9
            source.loc[source.Linea.eq("L1") & source.Operacion.eq("C"), "SAT"] = 1
            source.loc[source.Operacion.eq("X"), ["TBF", "TAP", "DES", "SAT", "NAP", "NPR"]] = 0
            source.to_csv(root / "data" / "datos_hackaton.csv", index=False)
            config.to_csv(root / "data" / "config_hackaton.csv", index=False)
            script = Path("app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(script, default_timeout=60).run()
            app.button(key="line_L1").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(any(s.label == "Balance horario del mapa" for s in app.selectbox))
            buttons = [b for b in app.button if b.key and b.key.startswith("operation_")]
            self.assertEqual({b.label for b in buttons}, {"A", "B", "C", "X"})
            next(b for b in buttons if b.label == "A").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Balance horario por revisar" in w.value for w in app.warning))
            self.assertFalse(any("Etiqueta de balance" in frame.value.columns for frame in app.dataframe))
            self.assertFalse(any(n.label == "Banda orientativa de balance (min)" for n in app.number_input))
            # La fuente en disco conserva todos los registros y tiempos originales.
            pd.testing.assert_frame_equal(pd.read_csv(root / "data" / "datos_hackaton.csv"), source)

    def test_filters_sort_and_grid_preserve_selection(self):
        app = self.app()
        app.selectbox(key="map_order").set_value("Por urgencia de reparación").run()
        buttons = [b for b in app.button if b.key and b.key.startswith("operation_")]
        self.assertEqual(buttons[0].label, "B")
        app.selectbox(key="map_signal").set_value("Parada propia").run()
        buttons = [b for b in app.button if b.key and b.key.startswith("operation_")]
        self.assertEqual([b.label for b in buttons], ["B"])
        app.button(key="toggle_map").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state["map_expanded"])
        app.selectbox(key="map_signal").set_value("Todas").run()
        self.assertEqual(len([b for b in app.button if b.key and b.key.startswith("operation_")]), 4)

    def test_summary_only_selects_lines_without_details_or_downloads(self):
        app = AppTest.from_string(self.script, default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertEqual([b.label for b in app.button], ["Ver operaciones", "Ver operaciones"])
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertEqual([m.value for m in app.metric], ["4", "0"])
        self.assertFalse(app.dataframe)
        self.assertFalse(any(s.label == "Línea" for s in app.selectbox))
        self.assertFalse(any(r.label == "Sección" for r in app.radio))
        self.assertFalse(any(e.label == "Cómo interpretar los resultados" for e in app.expander))
        for block in app.get("download_button"):
            self.assertEqual(block.proto.label, "Descargar indicadores de esta línea")

    def test_no_alerts_subfilters_and_adjustable_availability(self):
        app = AppTest.from_string(self.script, default_timeout=60).run()
        app.button(key="line_L2").click().run()
        app.selectbox(key="map_order").set_value("Por urgencia de reparación").run()
        app.selectbox(key="map_signal").set_value("Funcionamiento aceptable").run()
        app.selectbox(key="map_no_alerts").set_value("Elemento lento").run()
        self.assertEqual([b.label for b in app.button if b.key and b.key.startswith("operation_")], ["A"])
        app.selectbox(key="map_no_alerts").set_value("Buen funcionamiento").run()
        self.assertFalse([b for b in app.button if b.key and b.key.startswith("operation_")])
        next(n for n in app.number_input if n.label == "Objetivo de funcionamiento / TR (%)").set_value(99.0).run()
        app.selectbox(key="map_signal").set_value("Parada propia").run()
        self.assertFalse(app.exception)
        self.assertEqual([b.label for b in app.button if b.key and b.key.startswith("operation_")], ["A"])

    def test_analysis_menu_stays_below_map_and_line_download_is_not_repeated(self):
        app = self.app()
        menu = app.radio(key="line_analysis")
        self.assertEqual(menu.options, ["Microparadas", "Máquinas más problemáticas", "Tiempos todas las máquinas"])
        for option in menu.options:
            app.radio(key="line_analysis").set_value(option).run()
            self.assertFalse(app.exception)
            self.assertFalse(any(e.label == "Cómo interpretar los resultados" for e in app.expander))
            self.assertEqual(app.header[0].value, "Mapa de operaciones")
            self.assertEqual(sum(e.proto.label == "Descargar indicadores de esta línea"
                                 for e in app.get("download_button")), 0)
        app.button(key="back_to_lines").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.header[0].value, "Elige una línea")

    def test_line_selection_orders_by_problem_count_instead_of_name(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            source, config, *_ = fixture()
            source.loc[source.Linea.eq("L1"), ["TBF", "TAP", "DES", "SAT", "NAP", "NPR"]] = [22, 0, 0, 0, 0, 2000]
            source.loc[source.Linea.eq("L2"), ["TBF", "TAP", "DES", "SAT", "NAP", "NPR"]] = [10, 12, 0, 0, 1, 1000]
            source.to_csv(root / "data" / "datos_hackaton.csv", index=False)
            config.to_csv(root / "data" / "config_hackaton.csv", index=False)
            script = Path("app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(script, default_timeout=60).run()
            self.assertFalse(app.exception)
            self.assertEqual([b.key for b in app.button], ["line_L2", "line_L1"])
            self.assertEqual([m.value for m in app.metric], ["1", "0"])
            app.button(key="line_L2").click().run()
            self.assertFalse(app.exception)
            self.assertEqual([b.label for b in app.button if b.key and b.key.startswith("operation_")], ["A"])

    def test_priority_review_is_inside_line_below_map_and_survives_filters(self):
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
            self.assertNotIn("Revisión de datos", [s.value for s in app.header])
            app.button(key="line_L1").click().run()
            self.assertFalse(app.exception)
            app.radio(key="line_analysis").set_value("Máquinas más problemáticas").run()
            self.assertIn("Revisión de datos", [s.value for s in app.header])
            headers = [s.value for s in app.header]
            self.assertLess(headers.index("Revisión de datos"), headers.index("Análisis de la línea"))
            self.assertEqual(headers.count("Revisión de datos"), 1)
            self.assertNotIn("Patrón de paradas y línea de actuación", [s.value for s in app.subheader])
            self.assertEqual(app.header[0].value, "Mapa de operaciones")
            labels = [e.label for e in app.expander]
            for label in ["Sin producción · 1 máquinas", "Revisar datos · 1 máquinas", "Sin datos · 1 máquinas"]:
                self.assertIn(label, labels)
            review = next(e for e in app.expander if e.label == "Revisar datos · 1 máquinas")
            self.assertEqual(len(review.get("image")), 0)
            self.assertFalse(any("jefe" in m.value.lower() for m in app.markdown))
            self.assertIn("Paradas totales propias · 1 máquinas", labels)
            app.selectbox(key="map_signal").set_value("Otros").run()
            app.selectbox(key="map_review").set_value("Sin datos").run()
            self.assertEqual([b.label for b in app.button if b.key and b.key.startswith("operation_")], ["D"])
            app.selectbox(key="map_review").set_value("Revisar datos").run()
            self.assertEqual([b.label for b in app.button if b.key and b.key.startswith("operation_")], ["F"])
            self.assertFalse(app.exception)
            self.assertIn("Revisión de datos", [s.value for s in app.header])


if __name__ == "__main__":
    unittest.main()
