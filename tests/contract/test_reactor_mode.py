import pytest

from tests.contract.test_v15_session import opened_session as opened_session


@pytest.mark.parametrize("kind", ["conversion", "equilibrium"])
def test_attached_reactions_disable_separator_fallback_and_enable_calculation(
    opened_session, tmp_path, kind,
):
    session, _, _, _ = opened_session
    session.create_case(tmp_path / "case.hsc")
    reactor = getattr(session, f"create_{kind}_reactor")("Reactor")
    reactor.IsIgnored = True
    reactions = session.create_reaction_set("Reactions")
    session.attach_reaction_set(reactor, reactions)
    assert reactor.ReactionSet is reactions
    assert reactor.ActAsSeparatorWhenCannotSolve is False
    assert reactor.IsIgnored is False


def test_ignored_reactor_still_stops_before_solver(opened_session, tmp_path):
    session, _, _, _ = opened_session
    session.create_case(tmp_path / "case.hsc")

    class RefusesChange:
        ActAsSeparatorWhenCannotSolve = False

        @property
        def IsIgnored(self):
            return True

        @IsIgnored.setter
        def IsIgnored(self, value):
            pass

    with pytest.raises(RuntimeError, match="IsIgnored did not accept False"):
        session.attach_reaction_set(RefusesChange(), object())


def test_typed_put_is_attempted_only_after_default_setter_readback_fails(
    opened_session, tmp_path, monkeypatch,
):
    session, _, _, _ = opened_session
    session.create_case(tmp_path / "case.hsc")

    class RequiresTypedPut:
        _oleobj_ = object()
        enabled = True
        IsIgnored = False

        @property
        def ActAsSeparatorWhenCannotSolve(self):
            return self.enabled

        @ActAsSeparatorWhenCannotSolve.setter
        def ActAsSeparatorWhenCannotSolve(self, value):
            pass

    calls = []

    def typed_put(reactor, member, enabled):
        calls.append((member, enabled))
        reactor.enabled = enabled

    monkeypatch.setattr("app.hysys.v15_session._put_typed_boolean", typed_put)
    reactor = RequiresTypedPut()
    session.attach_reaction_set(reactor, object())
    assert calls == [("ActAsSeparatorWhenCannotSolve", False)]
    assert reactor.ActAsSeparatorWhenCannotSolve is False
