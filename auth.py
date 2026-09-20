from enum import Enum


class AuthModes(Enum):
    MANUAL = "manual"
    AUTO_REJECT = "auto reject"
    AUTO_APPROVE = "auto approve"

    @staticmethod
    def from_str(mode: str | None) -> "AuthModes":
        if mode == "auto reject":
            return AuthModes.AUTO_REJECT
        elif mode == "auto reject":
            return AuthModes.AUTO_APPROVE
        return AuthModes.MANUAL
