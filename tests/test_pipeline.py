"""Casos de negocio sintéticos, sin depender de los datos privados."""

import unittest

import pandas as pd

from analysis import Settings, analyse
from cleaning import BALANCE_LABELS, DAY_KEYS, ROW_KEYS, VALUES, prepare_data, select_scenario


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = pd.DataFrame([["L1", "A", 1], ["L1", "B", 1]],
                                   columns=["Linea", "Operacion", "Orden_OP"])

    def data(self, rows):
        return pd.DataFrame(rows, columns=ROW_KEYS + VALUES)

    def base(self):
        return self.data([["L1", 2026, 40, 1, "A", 18, 2, 1, 1, 4, 1000],
                          ["L1", 2026, 40, 1, "B", 18, 2, 1, 1, 4, 1000]])

    def result(self, prepared, scenario="all"):
        rows, days = select_scenario(prepared, scenario)
        return analyse(rows, days, prepared.configuration)

    def test_identical_copies_are_not_double_counted(self):
        original = self.base()
        copied = pd.concat([original, original.iloc[[0]]], ignore_index=True)
        prepared = prepare_data(copied, self.config)
        self.assertEqual(len(prepared.duplicates), 1)
        self.assertEqual(prepared.records.TAP.sum(), 4)
        self.assertNotIn("Source_Row", original)

    def test_conflicting_daily_records_are_quarantined(self):
        original = self.base()
        changed = original.iloc[[0]].copy()
        changed["TAP"] = 5
        prepared = prepare_data(pd.concat([original, changed], ignore_index=True), self.config)
        self.assertEqual(len(prepared.quarantine), 2)
        self.assertFalse(prepared.days.complete_coverage.iloc[0])
        missing = self.result(prepared).operations.set_index("Operacion").loc["A"]
        self.assertEqual(missing["status"], "Sin datos")

    def test_whole_line_stop_is_not_automatically_a_holiday(self):
        stopped = self.base()
        stopped[["TBF", "NPR", "NAP", "DES", "SAT"]] = 0
        stopped["TAP"] = 22
        prepared = prepare_data(stopped, self.config)
        self.assertEqual(prepared.days.day_status.iloc[0], "unconfirmed")
        self.assertEqual(len(select_scenario(prepared, "all")[0]), 2)
        self.assertTrue(self.result(prepared, "provisional").operations.empty)

    def test_calendar_preserves_a_planned_total_stop(self):
        stopped = self.base()
        stopped[["TBF", "NPR", "NAP", "DES", "SAT"]] = 0
        stopped["TAP"] = 22
        calendar = pd.DataFrame([["L1", 2026, 40, 1, 1]], columns=DAY_KEYS + ["Planned_Production"])
        prepared = prepare_data(stopped, self.config, calendar=calendar)
        self.assertEqual(prepared.days.day_status.iloc[0], "planned")
        self.assertEqual(len(select_scenario(prepared)[0]), 2)

    def test_one_station_stopped_does_not_exclude_the_day(self):
        source = self.base()
        source.loc[0, ["TBF", "NPR", "NAP", "DES", "SAT"]] = 0
        source.loc[0, "TAP"] = 22
        prepared = prepare_data(source, self.config)
        self.assertEqual(prepared.days.day_status.iloc[0], "unknown")
        self.assertEqual(len(select_scenario(prepared)[0]), 2)

    def test_calendar_closed_but_recorded_activity_needs_review(self):
        calendar = pd.DataFrame([["L1", 2026, 40, 1, 0]], columns=DAY_KEYS + ["Planned_Production"])
        prepared = prepare_data(self.base(), self.config, calendar=calendar)
        self.assertEqual(prepared.days.day_status.iloc[0], "calendar_conflict")
        self.assertEqual(len(select_scenario(prepared)[0]), 2)

    def test_mean_duration_uses_summed_time_and_count(self):
        source = pd.concat([self.base(), self.base().assign(Jour=2)], ignore_index=True)
        source.loc[source.Jour.eq(2), ["TBF", "TAP", "NAP"]] = [9, 1, 1]
        row = self.result(prepare_data(source, self.config)).operations.iloc[0]
        self.assertAlmostEqual(row.mean_stop_minutes, 36)  # 3 h * 60 / 5, not mean(30, 60)
        self.assertAlmostEqual(row.availability_pct, 90)
        self.assertTrue(row.stop_duration_reliable)

    def test_incompatible_counters_do_not_support_microstop_classification(self):
        source = pd.concat([self.base(), self.base().assign(Jour=2, NAP=0)], ignore_index=True)
        row = self.result(prepare_data(source, self.config)).operations.iloc[0]
        self.assertFalse(row.stop_duration_reliable)
        self.assertFalse(row.short_frequent_signal)

    def test_zero_stop_count_has_undefined_mean(self):
        row = self.result(prepare_data(self.base().assign(NAP=0), self.config)).operations.iloc[0]
        self.assertTrue(pd.isna(row.mean_stop_minutes))

    def test_time_tolerance_boundary_is_not_a_float_false_positive(self):
        source = self.base().assign(TBF=20, TAP=1, SAT=0)
        source["DES"] = [0.9, 1.1]  # 21,9 y 22,1 h: ambos están en la frontera.
        prepared = prepare_data(source, self.config)
        self.assertFalse(prepared.records.time_reference_mismatch.any())
        source["DES"] = [0.89, 1.11]
        prepared = prepare_data(source, self.config)
        self.assertTrue(prepared.records.time_reference_mismatch.all())

    def test_hour_balance_labels_cover_all_four_cases(self):
        source = self.data([
            ["L1", 2026, 40, 1, "A", 20, 2, 0, 0, 2, 1000],
            ["L1", 2026, 40, 1, "B", 19, 2, 0, 0, 2, 1000],
            ["L1", 2026, 40, 2, "A", 20, 2, 1, 0, 2, 1000],
            ["L1", 2026, 40, 2, "B", 0, 0, 0, 0, 0, 0],
        ])
        before = source.copy(deep=True)
        prepared = prepare_data(source, self.config)
        self.assertEqual(prepared.records.balance_label.tolist(), list(BALANCE_LABELS))
        pd.testing.assert_frame_equal(source, before)
        self.assertEqual(prepared.records.TBF.sum(), before.TBF.sum())

    def test_balance_band_boundary_and_custom_units(self):
        source = self.base().assign(TBF=20, TAP=1, SAT=0)
        source["DES"] = [0.98, 1.02]
        self.assertTrue(prepare_data(source, self.config).records.balance_label.eq(BALANCE_LABELS[0]).all())
        source["DES"] = [0.979, 1.021]
        self.assertEqual(prepare_data(source, self.config).records.balance_label.tolist(), [BALANCE_LABELS[1], BALANCE_LABELS[2]])
        source[["TBF", "TAP", "DES", "SAT"]] *= 60
        prepared = prepare_data(source, self.config, time_unit="minutes", balance_tolerance_hours=0.03)
        self.assertTrue(prepared.records.balance_label.eq(BALANCE_LABELS[0]).all())

    def test_opposite_daily_deviations_do_not_cancel_the_warning(self):
        source = pd.concat([self.base(), self.base().assign(Jour=2)], ignore_index=True)
        source.loc[source.Operacion.eq("A") & source.Jour.eq(1), "TBF"] = 17
        source.loc[source.Operacion.eq("A") & source.Jour.eq(2), "TBF"] = 19
        prepared = prepare_data(source, self.config)
        row = self.result(prepared).operations.set_index("Operacion").loc["A"]
        self.assertEqual(row.TR, 44)
        self.assertEqual(row.balance_deficit_days, 1)
        self.assertEqual(row.balance_excess_days, 1)
        self.assertEqual(row.balance_review_days, 2)

    def test_balance_uses_calendar_reference_without_filling_time(self):
        source = self.base().assign(TBF=18, TAP=2, DES=0, SAT=0)
        calendar = pd.DataFrame([["L1", 2026, 40, 1, 1, 20]],
                                columns=DAY_KEYS + ["Planned_Production", "Planned_Hours"])
        prepared = prepare_data(source, self.config, calendar=calendar)
        self.assertTrue(prepared.records.balance_label.eq(BALANCE_LABELS[0]).all())
        self.assertTrue(prepared.records.reference_hours.eq(20).all())
        self.assertTrue(prepared.records.recorded_hours.eq(20).all())

    def test_unit_conversion_and_parallel_order(self):
        source = self.base()
        source[["TBF", "TAP", "DES", "SAT"]] *= 60
        prepared = prepare_data(source, self.config, time_unit="minutes")
        self.assertAlmostEqual(prepared.records.TAP.sum(), 4)
        self.assertEqual(prepared.configuration.Orden_OP.nunique(), 1)

    def test_missing_calendar_day_is_not_zero_production(self):
        calendar = pd.DataFrame([["L1", 2026, 40, 1, 1], ["L1", 2026, 40, 2, 1]],
                                columns=DAY_KEYS + ["Planned_Production"])
        prepared = prepare_data(self.base(), self.config, calendar=calendar)
        row = self.result(prepared).operations.iloc[0]
        self.assertEqual(row.expected_days, 2)
        self.assertEqual(row.observed_days, 1)
        self.assertEqual(row["status"], "Revisar datos")

    def test_line_and_operation_joint_key(self):
        source = pd.concat([self.base(), self.base().assign(Linea="L2")], ignore_index=True)
        config = pd.concat([self.config, self.config.assign(Linea="L2")], ignore_index=True)
        result = self.result(prepare_data(source, config))
        self.assertEqual(len(result.operations), 4)
        self.assertEqual(len(result.lines), 2)

    def test_recurrence_includes_induced_stops(self):
        source = self.base().assign(TBF=12, TAP=0, DES=10, SAT=0, NAP=0)
        operations = self.result(prepare_data(source, self.config)).operations
        self.assertTrue(operations.recurrence_des.eq(1).all())
        self.assertTrue(operations.recurrence_own.eq(0).all())

    def test_invalid_calendar_and_settings_are_rejected(self):
        calendar = pd.DataFrame([["L1", 2026, 40, 1, 0]] * 2,
                                columns=DAY_KEYS + ["Planned_Production"])
        with self.assertRaises(ValueError):
            prepare_data(self.base(), self.config, calendar=calendar)
        prepared = prepare_data(self.base(), self.config)
        rows, days = select_scenario(prepared)
        with self.assertRaises(ValueError):
            analyse(rows, days, prepared.configuration, Settings(short_stop_minutes=20, long_stop_minutes=15))


if __name__ == "__main__":
    unittest.main()
