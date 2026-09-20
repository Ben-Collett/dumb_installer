from enum import Enum


class HookResult:
    def success(self) -> bool:
        raise NotImplementedError()

    def get_message(self) -> str:
        raise NotImplementedError()


class HookSuccess(HookResult):
    def success(self) -> bool:
        return True

    def get_message(self) -> str:
        return "success"


class HookFailure(HookResult):
    def __init__(self, msg: str):
        self.msg: str = msg

    def success(self) -> bool:
        return False

    def get_message(self) -> str:
        return self.msg
