"""Casos de impacto, ausencia de control y paradas fuera del ranking productivo."""

import unittest

import pandas as pd

from analysis import Settings, analyse
from cleaning import DAY_KEYS, ROW_KEYS, VALUES, prepare_data, select_scenario
from diagnostics import (critical_candidates, impact_pairs, impact_summary, microstop_assessment,
                         priority_figure, total_stops)


class DiagnosticTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
