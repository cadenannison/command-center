"""The real TokenSource: the operating system's cryptographic random source."""

import secrets

MIN_TOKEN_BYTES = 16  # 128 bits: nothing that guards access may carry less


class SystemTokenSource:
    """TokenSource backed by `secrets`, which reads the OS random source."""

    def new_token(self, num_bytes: int) -> str:
        if num_bytes < MIN_TOKEN_BYTES:
            msg = f"A token needs at least {MIN_TOKEN_BYTES} bytes of entropy, got {num_bytes}"
            raise ValueError(msg)
        return secrets.token_urlsafe(num_bytes)
