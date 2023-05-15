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


def Help():
    print(format({
        'app': 'Create New Package',
        'install renus/user/*': 'Install Apps',
        'install -update renus/user/*': 'Update Apps',
        'backup': 'Backing up the entire project',
        'copy': 'Get a copy of the app to upload to the server',
        'permission': 'Add All Permissions to DB',
        'default super_admin': 'Create Super Admin'
    },
        '{:<{}}', '{:<{}}', '\n\n', ' | '))
