from log_utils import print_info


class UserPrompt:
    def yes_or_no_prompt(self, msg: str) -> bool:
        response = input(msg+"(y or n)").strip().lower()
        while True:
            if response == "y" or response == "yes":
                return True
            elif response == "no" or response == "n":
                return False
            print_info("invalid response: {response}, reply with y or n:")
            response = input(msg).strip().lower()
