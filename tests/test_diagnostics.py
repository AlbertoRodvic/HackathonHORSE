"""Casos de impacto, ausencia de control y paradas fuera del ranking productivo."""

import unittest

import pandas as pd

from analysis import Settings, analyse
from cleaning import DAY_KEYS, ROW_KEYS, VALUES, prepare_data, select_scenario
from diagnostics import (critical_candidates, impact_pairs, impact_summary, microstop_assessment,
                         investigation_figure, priority_figure, total_stops, microstop_points,
                         microstop_figure, stop_action_plan, recurrence_matrix)


class DiagnosticTests(unittest.TestCase):
    def test_runtime_chart_uses_the_same_metric_as_its_filter(self):
        _, _, result = self.fixture()
        operations = result.operations.loc[result.operations.eligible & result.operations.TBF_pct.lt(90)]
        fig = investigation_figure(operations, Settings(), metric="TBF_pct")
        expected = operations.sort_values(["TBF_pct", "Operacion"])
        self.assertEqual([p.get_width() for p in fig.axes[0].patches], expected.TBF_pct.tolist())
        self.assertTrue(all(p.get_width() < 90 for p in fig.axes[0].patches))
        self.assertEqual(fig.axes[0].get_xlabel(), "Funcionamiento / TR (%)")
        self.assertNotEqual(expected.TBF_pct.tolist(), expected.availability_pct.tolist())

    def test_microstop_plot_is_one_point_per_operation_and_rejects_duplicates(self):
        _, _, result = self.fixture()
        # La operación A tiene media fiable en el periodo; los días no son puntos adicionales.
        points = microstop_points(result.operations)
        fig = microstop_figure(result.operations, Settings())
        self.assertEqual(len(fig.axes[0].collections[0].get_offsets()), len(points))
        self.assertLessEqual(len(points), result.operations.Operacion.nunique())
        with self.assertRaises(ValueError):
            microstop_points(pd.concat([result.operations, result.operations.iloc[[0]]]))

    def test_action_template_covers_four_disjoint_cases(self):
        operations = pd.DataFrame({"Linea": ["L"] * 4, "Operacion": list("ABCD"), "eligible": [True] * 4,
            "stop_duration_reliable": [True] * 4, "mean_stop_minutes": [1, 5, 1, 5],
            "fpm": [100, 100, 10, 10], "frequency_p75": [50] * 4, "TAP": [4, 3, 2, 1],
            "short_frequent_signal": [True, False, False, False]})
        cases = stop_action_plan(operations, Settings())
        self.assertEqual([c["count"] for c in cases], [1, 1, 1, 1])
        self.assertEqual([c["operations"] for c in cases], list("ABCD"))
        self.assertEqual(sum(c["tap_hours"] for c in cases), 10)

    def test_recurrence_only_keeps_significant_comparable_operations(self):
        _, _, result = self.fixture()
        weekly = result.weekly.copy()
        matrix = recurrence_matrix(weekly, "DES", Settings())
        self.assertEqual(matrix.index.tolist(), ["B"])
        weekly.loc[weekly.Operacion.eq("B"), "eligible"] = False
        self.assertTrue(recurrence_matrix(weekly, "DES", Settings()).empty)

    def fixture(self):
        config = pd.DataFrame([["L", "A", 1], ["L", "B", 2], ["L", "X", 2], ["L", "MISSING", 3]],
                              columns=["Linea", "Operacion", "Orden_OP"])
        rows = []
        for day in range(1, 7):
            rows += [["L", 2026, 40, day, "A", 10 if day <= 3 else 20, 10 if day <= 3 else 0, 1, 1, 10 if day <= 3 else 0, 1000],
                     ["L", 2026, 40, day, "B", 12 if day <= 3 else 20, 0, 9 if day <= 3 else 1, 1, 0, 1000],
                     ["L", 2026, 40, day, "X", 20, 0, 1, 1, 0, 1000]]
        prepared = prepare_data(pd.DataFrame(rows, columns=ROW_KEYS + VALUES), config)
        r, d = select_scenario(prepared)
        return config, r, analyse(r, d, config)

    def test_impact_compares_all_operations_and_exposes_missing_data(self):
        config, records, result = self.fixture()
        candidates = critical_candidates(result.operations, records)
        pairs = impact_pairs(candidates, result.operations, records, Settings())
        b = pairs.loc[pairs.operation.eq("B") & pairs.signal.eq("DES")].iloc[0]
        self.assertEqual((b.own_signal_days, b.control_days), (3, 3))
        self.assertAlmostEqual(b.difference_pp, 100 * 8 / 22)
        self.assertTrue(b.positive_association)
        self.assertEqual(set(pairs.operation), {"B", "X", "MISSING"})
        self.assertTrue(pairs.relation.eq("Conexión por confirmar").all())
        missing = pairs.loc[pairs.operation.eq("MISSING")]
        self.assertTrue(missing.paired_days.eq(0).all())
        self.assertTrue(missing.difference_pp.isna().all())
        summary = impact_summary(pairs).iloc[0]
        self.assertEqual(summary.other_operations, 3)
        self.assertEqual(summary.positive_operations, 1)
        self.assertEqual(summary.unobserved_operations, 1)
        self.assertEqual(summary.compatible_positive_operations, 0)

    def test_topology_respects_branches_and_signal_direction(self):
        _, records, result = self.fixture()
        links = pd.DataFrame([["L", "A", "B"]], columns=["Linea", "Origen", "Destino"])
        pairs = impact_pairs(critical_candidates(result.operations, records), result.operations, records, Settings(), links)
        b = pairs.loc[pairs.operation.eq("B")]
        self.assertTrue(b.loc[b.signal.eq("DES"), "relation"].str.startswith("Ruta compatible").all())
        self.assertTrue(b.loc[b.signal.eq("SAT"), "relation"].str.startswith("Dirección contraria").all())
        self.assertTrue(pairs.loc[pairs.operation.eq("X"), "relation"].str.startswith("Sin ruta").all())
        self.assertEqual(impact_summary(pairs).iloc[0].compatible_positive_operations, 1)

    def test_persistent_own_signal_does_not_invent_control_or_absence_of_effect(self):
        _, records, result = self.fixture()
        records.loc[records.Operacion.eq("A"), ["TBF", "TAP"]] = [10, 10]
        pairs = impact_pairs(result.operations.loc[result.operations.Operacion.eq("A")], result.operations, records, Settings())
        self.assertTrue(pairs.control_days.eq(0).all())
        self.assertFalse(pairs.comparison_available.any())
        self.assertTrue(pairs.wait_without_own_pct.isna().all())

    def test_total_stop_in_planned_day_is_candidate_even_without_any_production(self):
        config = pd.DataFrame([["L", "A", 1], ["L", "B", 2]], columns=["Linea", "Operacion", "Orden_OP"])
        source = pd.DataFrame([["L", 2026, 40, 1, "A", 0, 22, 0, 0, 0, 0],
                               ["L", 2026, 40, 1, "B", 0, 0, 22, 0, 0, 0]], columns=ROW_KEYS + VALUES)
        calendar = pd.DataFrame([["L", 2026, 40, 1, 1]], columns=DAY_KEYS + ["Planned_Production"])
        prepared = prepare_data(source, config, calendar=calendar)
        records, days = select_scenario(prepared)
        result = analyse(records, days, config)
        self.assertFalse(result.operations.eligible.any())
        self.assertEqual(critical_candidates(result.operations, records).Operacion.tolist(), ["A"])
        self.assertTrue(total_stops(records).investigate_total_stop.all())
        pairs = impact_pairs(critical_candidates(result.operations, records), result.operations, records, Settings())
        self.assertEqual(pairs.loc[pairs.signal.eq("DES"), "coincident_days"].iloc[0], 1)
        # Sin calendario, no se considera automáticamente una avería de toda la línea.
        p = prepare_data(source, config)
        self.assertFalse(total_stops(p.records).investigate_total_stop.any())

    def test_microstops_use_reliable_days_and_separate_relevance_from_large_breakdowns(self):
        config = pd.DataFrame([["L", "A", 1]], columns=["Linea", "Operacion", "Orden_OP"])
        source = pd.DataFrame([["L", 2026, 40, 1, "A", 20, 1, 1, 0, 120, 1000],
                               ["L", 2026, 40, 2, "A", 20, 1, 1, 0, 0, 1000]], columns=ROW_KEYS + VALUES)
        records = prepare_data(source, config).records
        summary, detail = microstop_assessment(records, Settings())
        row = summary.iloc[0]
        self.assertEqual(row.brief_frequent_days, 1)
        self.assertEqual(row.reliable_days, 1)
        self.assertAlmostEqual(row.tap_on_signal_days_pct, 100 / 44)
        self.assertTrue(row.significant)
        self.assertEqual(len(detail), 1)
        self.assertIn("No son averías grandes confirmadas", row.recommendation)
        stricter, _ = microstop_assessment(records, Settings(microstop_loss_threshold_pct=5))
        self.assertFalse(stricter.iloc[0].significant)

    def test_comparison_figure_keeps_same_operations_across_panels(self):
        _, _, result = self.fixture()
        fig = priority_figure(result.operations, Settings())
        self.assertEqual(len(fig.axes), 5)
        self.assertEqual([t.get_text() for t in fig.axes[0].get_yticklabels()], ["A"])

    def test_investigation_chart_keeps_review_machines_and_both_panels_aligned(self):
        operations = pd.DataFrame({"Linea": ["L"] * 5, "Operacion": ["A", "B", "C", "D", "E"],
                                   "availability_pct": [90, 20, 80, float("nan"), 70],
                                   "TAP": [1, 12, 3, 4, 5], "DES": [2, 3, 4, 5, 6], "SAT": [0, 1, 2, 3, 4]})
        fig = investigation_figure(operations, Settings())
        self.assertEqual(len(fig.axes), 2)
        self.assertEqual([tick.get_text() for tick in fig.axes[0].get_yticklabels()], ["B", "E", "C", "A", "D"])
        self.assertEqual(len(fig.axes[1].patches), 15)
        self.assertEqual(list(fig.axes[0].lines[0].get_xdata()), [90, 90])
        self.assertIn("Sin disponibilidad definida", [text.get_text() for text in fig.axes[0].texts])


if __name__ == "__main__":
    unittest.main()
