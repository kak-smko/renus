import shutil
import zipfile
from io import BytesIO

from renus.commands.help import bc
from renus.commands.install.build import _add_route, _add_admin_templates, _add_index_templates, _add_user_templates, \
    _add_cls, _add_imprt, _add_config
from renus.commands.install.service import request


def download(app, version, installed, isUpdate=False):
    if app in installed:
        if isUpdate and installed[app] == version:
            return version
        elif not isUpdate:
            return version

    print(f'{bc.OKGREEN}downloading {app}/{version}{bc.ENDC}')

    res = request(f'https://reapp.codenus.com/app/{app}/{version}')

    if res.status_code != 200:
        print(f'{bc.FAIL}download error{bc.ENDC}')
        return

    if app in installed:
        if isUpdate and installed[app] == res.headers['version']:
            print('   same version', res.headers['version'])
            return res.headers['version']
        elif not isUpdate:
            print('   currently installed version', installed[app])
            return res.headers['version']

    installed[app] = res.headers['version']
    f = zipfile.ZipFile(BytesIO(res.content))
    shutil.rmtree(f"extension/{app}", True)
    f.extractall(f"extension/{app}")
    if not isUpdate:
        install_app(app, installed)
    else:
        print(f'{bc.OKBLUE}   updated to version {res.headers["version"]}{bc.ENDC}')
    return res.headers['version']


def rewrite(installed):
    print('   rewrite installed')
    pre_line = ''
    with open('extension/install.py', 'r') as f:
        lines = f.readlines()
        for line in lines:
            if line.find('installed') != -1:
                break
            pre_line += line
    with open('extension/install.py', 'w') as f:
        f.write(pre_line)
        f.write('installed = {\n')
        for app, version in installed.items():
            f.write(f'  "{app}":"{version}",\n')
        f.write('}')


def install_app(app, installed):
    print(f'   install {app}')
    try:
        install = __import__(f"extension.{app.replace('/', '.')}.install", fromlist=[''])

    except Exception as exc:
        print('   ' + bc.WARNING + str(exc) + bc.ENDC)
        return

    if hasattr(install, 'dependencies'):
        print(f'   install {app} dependencies...')
        for dep in install.dependencies:
            download(dep, '*', installed)

    if hasattr(install, 'cls'):
        print(f'   add {app} class...')
        _add_cls(install,app)

    if hasattr(install, 'route'):
        print(f'   add {app} route...')
        _add_route(install,app)

    if hasattr(install, 'imprt'):
        print(f'   add {app} imports...')
        _add_imprt(install,app)

    if hasattr(install, 'admin_templates'):
        print(f'   add {app} admin_templates...')
        _add_admin_templates(install)

    if hasattr(install, 'index_templates'):
        print(f'   add {app} index_templates...')
        _add_index_templates(install)

    if hasattr(install, 'user_templates'):
        print(f'   add {app} user_templates...')
        _add_user_templates(install)

    if hasattr(install, 'config'):
        print(f'   add {app} config...')
        _add_config(install)

    if hasattr(install, 'setup'):
        print(f'   setup {app}...')
        install.setup()


def install_all(apps, installed, isUpdate):
    d = apps
    if isUpdate:
        d = installed
    for app, version in d.items():
        download(app, '*' if isUpdate else version, installed, isUpdate)


def run(args=None):
    print('start...')
    try:
        from extension.install import apps, installed
    except:
        apps = {}
        installed = {}
    isUpdate = False

    if args and '-update' in args:
        isUpdate = True
        args.remove('-update')

    if args is None or len(args) == 0:
        install_all(apps, installed, isUpdate)
        pass
    else:
        s = args[0].split('/')
        version = s[-1]
        s.pop(-1)

        download('/'.join(s), version, installed, isUpdate)
    rewrite(installed)

    print(f'{bc.OKBLUE}finished{bc.ENDC}')
