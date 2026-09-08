"""Offline routing tests: the shell must execute only the selected report."""
from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock

import streamlit as st
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"
LABELS = {"Monday": "Monday · Digital Credit", "Friday": "Friday · Bitcoin & Digital Credit"}


def select_report(app, report):
    """Send the same string widget event as a browser tab click.

    Streamlit 1.63 exposes tabs as blocks in AppTest, with no select() helper.
    Preserve other widget states instead of simulating a new browser session.
    """
    states = app._tree.get_widget_states()
    widget_id = app.session_state._state._key_id_mapper.get_id_from_key("weekly_report_tabs", None)
    if not widget_id:
        raise AssertionError("The report tabs must register a stateful widget")
    event = next((item for item in states.widgets if item.id == widget_id), None)
    if event is None:
        event = states.widgets.add()
        event.id = widget_id
    event.string_value = LABELS[report]
    return app._run(states)


class CombinedAppTests(TestCase):
    def setUp(self):
        self.calls = []
        self.adapters = {}
        modules = {}
        for report in LABELS:
            module = ModuleType(f"{report.lower()}_page")
            module.render = Mock(name=f"{report}.render", side_effect=self.renderer(report))
            modules[module.__name__] = module
            self.adapters[report] = module.render
        previous = {name: sys.modules.get(name) for name in modules}
        sys.modules.update(modules)

        def restore_adapters():
            # Restore only these adapters; retain modules Streamlit imports during a run.
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore_adapters)

    def renderer(self, report):
        def render():
            self.calls.append(report)
            # The guard must already agree before an adapter or its timers execute.
            if st.session_state.get("weekly_active_report") != report:
                raise AssertionError("Adapter rendered before its active-report guard was set")
            state_key = f"{report.lower()}_test_report"
            if state_key not in st.session_state:
                st.session_state[state_key] = {
                    "issuer": "MSTR" if report == "Monday" else "BTC",
                    "refreshes": 0,
                    "frozen_export": {"report": report, "close": 123.456789},
                }
            st.write(f"{report} adapter")

            def refresh():
                state = deepcopy(st.session_state[state_key])
                state["refreshes"] += 1
                st.session_state[state_key] = state

            st.button(f"Refresh {report}", key=f"{report.lower()}_test_refresh", on_click=refresh)
        return render

    def app(self, query=None):
        app = AppTest.from_file(str(APP), default_timeout=10)
        app.query_params.update(query or {})
        return app.run()

    def assert_selected(self, app, report):
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        self.assertEqual([tab.label for tab in app.tabs], list(LABELS.values()))
        self.assertEqual(app.session_state["weekly_report_tabs"], LABELS[report])
        self.assertEqual(app.session_state["weekly_active_report"], report)
        self.assertEqual(app.query_params["report"], [report.lower()])
        self.assertEqual([button.label for button in app.button], [f"Refresh {report}"])
        self.assertEqual(self.calls[-1], report)
        # Navigation state belongs to the shell, never to render() arguments.
        self.adapters[report].assert_called_with()

    def test_default_session_runs_only_monday(self):
        app = self.app()
        self.assert_selected(app, "Monday")
        self.assertEqual(self.calls, ["Monday"])
        self.adapters["Friday"].assert_not_called()
        self.assertNotIn("friday_test_report", app.session_state)

    def test_friday_deep_link_runs_only_friday(self):
        app = self.app({"report": "friday", "source": "bookmark"})
        self.assert_selected(app, "Friday")
        self.assertEqual(self.calls, ["Friday"])
        self.adapters["Monday"].assert_not_called()
        self.assertEqual(app.query_params["source"], ["bookmark"])
        self.assertNotIn("monday_test_report", app.session_state)

    def test_invalid_report_deep_link_falls_back_to_monday(self):
        app = self.app({"report": "unknown-report", "source": "bookmark"})
        self.assert_selected(app, "Monday")
        self.assertEqual(app.query_params["source"], ["bookmark"])
        self.assertEqual(self.calls, ["Monday"])

    def test_tab_events_keep_selection_query_and_active_guard_consistent(self):
        app = self.app({"report": "monday"})
        select_report(app, "Friday")
        self.assert_selected(app, "Friday")
        self.assertEqual(self.calls, ["Monday", "Friday"])
        # On an existing session, its actual selected tab wins over a stale URL.
        app.query_params["report"] = "monday"
        select_report(app, "Friday")
        self.assert_selected(app, "Friday")
        select_report(app, "Monday")
        self.assert_selected(app, "Monday")
        self.assertEqual(self.calls, ["Monday", "Friday", "Friday", "Monday"])

    def test_switches_and_refreshes_preserve_each_reports_durable_state(self):
        app = self.app()
        app.button(key="monday_test_refresh").click()
        select_report(app, "Monday")
        monday = deepcopy(app.session_state["monday_test_report"])
        self.assertEqual(monday["refreshes"], 1)
        select_report(app, "Friday")
        friday_frozen = deepcopy(app.session_state["friday_test_report"]["frozen_export"])
        app.button(key="friday_test_refresh").click()
        select_report(app, "Friday")
        self.assert_selected(app, "Friday")
        self.assertEqual(app.session_state["monday_test_report"], monday)
        self.assertEqual(app.session_state["friday_test_report"]["refreshes"], 1)
        self.assertEqual(app.session_state["friday_test_report"]["frozen_export"], friday_frozen)
        friday = deepcopy(app.session_state["friday_test_report"])
        select_report(app, "Monday")
        self.assert_selected(app, "Monday")
        self.assertEqual(app.session_state["monday_test_report"], monday)
        self.assertEqual(app.session_state["friday_test_report"], friday)
        self.assertEqual(self.calls, ["Monday", "Monday", "Friday", "Friday", "Monday"])

    def test_new_browser_session_uses_its_own_link_and_report_state(self):
        first = self.app({"report": "friday"})
        first.button(key="friday_test_refresh").click()
        select_report(first, "Friday")
        second = self.app({"report": "monday"})
        self.assert_selected(second, "Monday")
        self.assertEqual(second.session_state["monday_test_report"]["refreshes"], 0)
        self.assertNotIn("friday_test_report", second.session_state)
        self.assertEqual(first.session_state["weekly_active_report"], "Friday")
        self.assertEqual(first.session_state["friday_test_report"]["refreshes"], 1)
