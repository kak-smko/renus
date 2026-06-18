import os, sys,importlib

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def find_command(name):
    """Search for a command module in framework and project directories."""
    try:
        return importlib.import_module(f"commands.{name}.run")
    except ModuleNotFoundError:
        pass
        
    try:
        return importlib.import_module(f"renus.commands.{name}.run")
    except ModuleNotFoundError:
        pass
    
    
    return None
    
def run():
    clear_screen()
    arg = sys.argv
    
    if len(arg) < 2:
        from renus.commands.help import Help
        Help()
        return
    
    command_name = arg[1]
    module = find_command(command_name)
    
    if module is None:
        print(f"Error: Command '{command_name}' not found.")
        print("Run 'renus' without arguments to see available commands.\n")
        from renus.commands.help import Help
        Help()
        return
    
    args = arg[2:] if len(arg) > 2 else None
    
    try:
        if args:
            module.run(args)
        else:
            module.run()
    except Exception as e:
        print(f"\033[91mError running '{command_name}': {e}\033[0m")


def main():
    run()