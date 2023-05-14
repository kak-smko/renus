from renus.core.config import Config

app = Config('app')


class Cprint:

    def __init__(self, debug: bool = None) -> None:
        """
        @param debug: by default read debug mode from Config file
        """
        self._debug = app.get('debug', False) if debug is None else debug

    def print(self, txt):
        """
        print txt if debug mode is True
        """
        if self._debug:
            print(txt)

    @staticmethod
    def bold(txt):
        return f'\033[1m{txt}\033[0m'

    @staticmethod
    def italic(txt):
        return f'\033[3m{txt}\033[0m'

    @staticmethod
    def underline(txt):
        return f'\033[4m{txt}\033[0m'

    @staticmethod
    def mid_line(txt):
        return f'\033[9m{txt}\033[0m'

    @staticmethod
    def black(txt):
        return f'\033[30m{txt}\033[0m'

    @staticmethod
    def grey(txt):
        return f'\033[37m{txt}\033[0m'

    @staticmethod
    def red(txt):
        return f'\033[91m{txt}\033[0m'

    @staticmethod
    def green(txt):
        return f'\033[92m{txt}\033[0m'

    @staticmethod
    def yellow(txt):
        return f'\033[93m{txt}\033[0m'

    @staticmethod
    def blue(txt):
        return f'\033[94m{txt}\033[0m'

    @staticmethod
    def pink(txt):
        return f'\033[95m{txt}\033[0m'

    @staticmethod
    def cyan(txt):
        return f'\033[96m{txt}\033[0m'

    @staticmethod
    def white(txt):
        return f'\033[97m{txt}\033[0m'

    @staticmethod
    def bg_white(txt):
        return f'\033[7m{txt}\033[0m'

    @staticmethod
    def bg_black(txt):
        return f'\033[40m{txt}\033[0m'

    @staticmethod
    def bg_red(txt):
        return f'\033[41m{txt}\033[0m'

    @staticmethod
    def bg_green(txt):
        return f'\033[42m{txt}\033[0m'

    @staticmethod
    def bg_yellow(txt):
        return f'\033[43m{txt}\033[0m'

    @staticmethod
    def bg_blue(txt):
        return f'\033[44m{txt}\033[0m'

    @staticmethod
    def bg_pink(txt):
        return f'\033[45m{txt}\033[0m'

    @staticmethod
    def bg_cyan(txt):
        return f'\033[46m{txt}\033[0m'

    @staticmethod
    def bg_grey(txt):
        return f'\033[47m{txt}\033[0m'


if __name__ == "__main__":
    c = Cprint()
    c.print(c.bg_cyan('test ' + c.red('ok')))
