import importlib
from pathlib import Path


class bc:
    OKPINK = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def format(header,
                  left_format, cell_format, row_delim, col_delim):
    table = [[bc.OKPINK + 'command name' + bc.ENDC, bc.WARNING + 'description' + bc.ENDC]] + [
        [bc.OKGREEN + name + bc.ENDC, bc.OKCYAN + row + bc.ENDC] for name, row in header.items()]

    table_format = (len(header) + 1) * [[left_format] + len(header) * [cell_format]]

    col_widths = [max(
        len(format.format(cell, 0))
        for format, cell in zip(col_format, col))
        for col_format, col in zip(zip(*table_format), zip(*table))]
    return row_delim.join(
        col_delim.join(
            format.format(cell, width)
            for format, cell, width in zip(row_format, row, col_widths))
        for row_format, row in zip(table_format, table))


def discover_commands():
    """Discover all available commands from framework and project."""
    commands = {}
    
    # Framework built-in commands
    framework_dir = Path(__file__).parent
    for item in framework_dir.iterdir():
        if item.is_dir() and (item / 'run.py').exists() and not item.name.startswith('_'):
            try:
                mod = importlib.import_module(f"renus.commands.{item.name}.run")
                desc = getattr(mod, 'DESCRIPTION', f'Run {item.name} command')
                commands[item.name] = desc
            except Exception:
                commands[item.name] = f'Run {item.name} command'
    
    # Project-level custom commands
    project_commands = Path.cwd() / 'commands'
    if project_commands.exists():
        for item in project_commands.iterdir():
            if item.is_dir() and (item / 'run.py').exists() and not item.name.startswith('_'):
                try:
                    mod = importlib.import_module(f"commands.{item.name}.run")
                    desc = getattr(mod, 'DESCRIPTION', f'[custom] Run {item.name} command')
                    commands[item.name] = desc
                except Exception:
                    commands[item.name] = f'[custom] Run {item.name} command'
    
    return commands

def Help():
    commands = discover_commands()
    print(format(commands, '{:<{}}', '{:<{}}', '\n\n', ' | '))
