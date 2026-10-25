from pathlib import Path
from typing import Any


def open_case_moniker(case_path: Path, progid: str) -> tuple[Any, Any, bool]:
    """Open a local HYSYS case through its file moniker.

    HYSYS V15 publishes cases through the Windows running object table. Opening the
    copied case with ``GetObject`` is the verified V15 path; ``SimulationCases.Open``
    returns access denied on the licensed workstation used for this application.

    The ownership flag is deliberately conservative. If any HYSYS application was
    active before the file was opened, callers must not quit the returned application.
    """
    from win32com.client import GetActiveObject, GetObject

    case_path = Path(case_path).resolve()
    if not case_path.is_file():
        raise FileNotFoundError(case_path)

    application_was_active = False
    try:
        GetActiveObject(progid)
        application_was_active = True
    except Exception:
        pass

    simulation_case = GetObject(str(case_path))
    application = simulation_case.Application
    return simulation_case, application, not application_was_active
