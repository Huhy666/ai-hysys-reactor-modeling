from app.hysys.introspection import collect_reactor_control_properties


class Reactor:
    _prop_map_get_ = {"ActAsSeparatorWhenCannotSolve": None, "Ignored": None}

    def __init__(self):
        self.ActAsSeparatorWhenCannotSolve = True
        self.Ignored = False
        self.name = "Conversion Reactor"


def test_control_probe_reads_actual_members_without_changing_them():
    reactor = Reactor()
    report = collect_reactor_control_properties(reactor)
    assert report["ActAsSeparatorWhenCannotSolve"]["value"] is True
    assert report["Ignored"]["value"] is False
    assert "name" not in report
    assert reactor.ActAsSeparatorWhenCannotSolve is True


def test_missing_controls_are_not_invented():
    assert collect_reactor_control_properties(object()) == {}
