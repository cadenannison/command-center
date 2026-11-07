"""Error classes: one per failure class, all catchable as one family."""

import pytest

from command_center.core.errors import AuthExpired, FatalError, SourceError, TransientError

MESSAGE = "Failed to fetch Canvas courses: token rejected (401)"


@pytest.mark.parametrize("error_class", [AuthExpired, TransientError, FatalError])
def test_each_failure_class_is_a_source_error(error_class: type[SourceError]) -> None:
    assert issubclass(error_class, SourceError)


def test_failure_classes_are_distinct() -> None:
    assert not issubclass(AuthExpired, TransientError)
    assert not issubclass(TransientError, FatalError)
    assert not issubclass(FatalError, AuthExpired)


def test_error_carries_its_message() -> None:
    with pytest.raises(AuthExpired, match="token rejected"):
        raise AuthExpired(MESSAGE)
