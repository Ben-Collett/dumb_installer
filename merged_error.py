class MergedError:
    def __init__(self):
        self.errors: list[str] = []

    def add_error(self, msg: str):
        self.errors.append(msg)

    def has_erred(self):
        return len(self.errors) > 0

    def add_error_if(self, condition: bool, message: str):
        if condition:
            self.errors.append(message)

    def on_missing_toml_field(self, field: str, section: str, data: dict):
        if field not in data:
            self.errors.append(f"missing '{field}' in [{section}]")

    def print_and_exit_if_erred(self, exit_code=1):
        if self.has_erred():
            self.print_messages()
            exit(exit_code)

    def print_messages(self):
        for error in self.errors:
            print(error)
