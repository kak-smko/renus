import os, sys,platform

from renus.commands.help import Help

def run():
    arg = sys.argv
    if platform.system() == 'Windows':
        os.system('cls')
    else:
        os.system('clear')
    if len(arg) < 2:
        Help()
    if len(arg) == 2:
        getattr(__import__(f"renus.commands.{arg[1]}.run", fromlist=['']), 'run')()
    elif len(arg) > 2:
        getattr(__import__(f"renus.commands.{arg[1]}.run", fromlist=['']), 'run')(arg[2:])


def main():
    run()