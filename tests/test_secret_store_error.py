"""SecretStoreError lives in core so services and adapters can share it."""

from command_center.core.errors import SecretStoreError, SourceError


def test_is_an_exception_but_not_a_source_error() -> None:
    assert issubclass(SecretStoreError, Exception)
    assert not issubclass(SecretStoreError, SourceError)


def test_carries_its_message() -> None:
    error = SecretStoreError("Failed to read secret: keychain is locked")

    assert str(error) == "Failed to read secret: keychain is locked"
