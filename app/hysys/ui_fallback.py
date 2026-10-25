"""Narrow, optional runtime UI bridge for the verified V15 separator checkbox.

Runs on the HYSYS workstation when the user launches the application. Never
clicks coordinates or operates a window outside the selected HYSYS process.
"""

import re
import time
from typing import Any

LABEL = "Act as a Separator When Cannot Solve"


def unique(items: list[Any], label: str) -> Any:
    if len(items) != 1:
        raise RuntimeError(f"{label}: expected one matching control, found {len(items)}")
    return items[0]


def disable_separator_checkbox(case_filename: str, reactor_name: str) -> dict[str, Any]:
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        pattern = re.compile(r"^" + re.escape(case_filename) + r"\s+-\s+Aspen HYSYS", re.I)
        main = unique([window for window in desktop.windows()
                       if pattern.search(window.window_text())], "active HYSYS case")
        process = main.process_id()
        main.set_focus()

        def property_views():
            scopes = [main]
            scopes.extend(window for window in desktop.windows(process=process)
                          if window.window_text().startswith(reactor_name + ":"))
            return scopes

        def checkboxes():
            found = {}
            for scope in property_views():
                for control in scope.descendants(control_type="CheckBox"):
                    if control.window_text().casefold() == LABEL.casefold():
                        found[control.element_info.runtime_id.__str__()] = control
            return list(found.values())

        matches = checkboxes()
        if not matches:
            # Open the existing operation through its exact tree name, never Add Operation.
            operations = [item for item in main.descendants(control_type="TreeItem")
                          if item.window_text() == "UnitOps"]
            if len(operations) == 1:
                operations[0].expand()
            operation = unique([item for item in main.descendants(control_type="TreeItem")
                                if item.window_text() == reactor_name], "reactor tree item")
            operation.double_click_input()
            time.sleep(0.3)
            views = property_views()
            tabs = [item for view in views for item in view.descendants(control_type="TabItem")
                    if item.window_text() == "Design"]
            # Deduplicate scopes before touching an exact control.
            tabs = list({str(item.element_info.runtime_id): item for item in tabs}.values())
            unique(tabs, "reactor Design tab").select()
            parameters = [item for view in property_views() for item in view.descendants()
                          if item.window_text() == "Parameters"]
            parameters = list({str(item.element_info.runtime_id): item
                               for item in parameters}.values())
            unique(parameters, "reactor Parameters page").click_input()
            time.sleep(0.2)
            matches = checkboxes()
        checkbox = unique(matches, "separator fallback checkbox")
        if checkbox.get_toggle_state() == 1:
            checkbox.toggle()
        if checkbox.get_toggle_state() != 0:
            raise RuntimeError("separator checkbox did not become unchecked")
        return {"success": True, "method": "uia_exact_checkbox", "process_id": process}
    except Exception as exc:
        return {"success": False, "method": "uia_exact_checkbox",
                "error": f"{type(exc).__name__}: {exc}"}
