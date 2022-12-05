import json
import shutil
import typing
from email.message import Message
from io import BytesIO
import zipfile
import urllib.request
import urllib.error
from renus.commands.help import bc

class Response(typing.NamedTuple):
    content: bytes
    head: Message
    status_code: int
    @property
    def headers(self):
        res={}
        h=self.head.items()
        for item in h:
            res[item[0]]=item[1]
        return res



def request(
    url: str
) -> Response:
    method = 'GET'

    headers = {"Accept": "*"}

    httprequest = urllib.request.Request(
        url,  headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(httprequest) as httpresponse:
            response = Response(
                head=httpresponse.headers,
                status_code=httpresponse.status,
                content=httpresponse.read()
            )
    except urllib.error.HTTPError as e:
        response = Response(
            content=bytes(e.reason),
            head=e.headers,
            status_code=e.code
        )

    return response

def download(app, version, installed,isUpdate=False):
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
            print('   same version',res.headers['version'])
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
    if hasattr(install, 'routes'):
        print(f'   add {app} routes...')
        with open('./routes/index.py', 'r') as file:
            all = file.read()
            routes = ''
            for route in install.routes:
                routes += 'import ' + route + '\n'
            all = all.replace('import routes.api', f'{routes}import routes.api')
            with open('./routes/index.py', 'w') as b:
                b.write(all)

    if hasattr(install, 'admin_templates'):
        print(f'   add {app} admin_templates...')
        with open('./frontend/src/router/admin.js', 'r') as file:
            all = file.read()
            for item in install.admin_templates:
                all = all.replace('/* {{place new import}} */',
                                  '/* {{place new import}} */\nconst ' + item.get('name',
                                                                                  'test') + ' = () => import("' + item.get(
                                      'file', 'test') + '");')
                all = all.replace('/* {{place new Route}} */',
                                  '/* {{place new Route}} */\n' + item.get('path', '{}') + ',')

            with open('./frontend/src/router/admin.js', 'w') as b:
                b.write(all)

    if hasattr(install, 'index_templates'):
        print(f'   add {app} index_templates...')
        with open('./frontend/src/router/index.js', 'r') as file:
            all = file.read()
            for item in install.index_templates:
                all = all.replace('/* {{place new import}} */',
                                  '/* {{place new import}} */\nconst ' + item.get('name',
                                                                                  'test') + ' = () => import("' + item.get(
                                      'file', 'test') + '");')
                all = all.replace('/* {{place new Route home}} */',
                                  '/* {{place new Route home}} */\n' + item.get('path', '') + ',')
            with open('./frontend/src/router/index.js', 'w') as b:
                b.write(all)

    if hasattr(install, 'user_templates'):
        print(f'   add {app} user_templates...')
        with open('./frontend/src/router/index.js', 'r') as file:
            all = file.read()
            for item in install.user_templates:
                all = all.replace('/* {{place new import}} */',
                                  '/* {{place new import}} */\nconst ' + item.get('name',
                                                                                  'test') + ' = () => import("' + item.get(
                                      'file', 'test') + '");')
                all = all.replace('/* {{place new Route user}} */',
                                  '/* {{place new Route user}} */\n' + item.get('path', '') + ',')
            with open('./frontend/src/router/index.js', 'w') as b:
                b.write(all)

    if hasattr(install, 'db'):
        print(f'   add {app} DB...')
        if install.db:
            for m, db in install.db.items():
                m = m.split('.')
                name = m[-1]
                m.pop(-1)
                path = '.'.join(m)
                model = __import__(path, fromlist=[''])
                with open(f'extension/{app}/{db}', 'r') as db:
                    d = json.loads(db.read())
                    model = getattr(model, name)('app')
                    for item in d:
                        model.create(item)


def install_all(apps, installed,isUpdate):
    for app, version in apps.items():
        download(app, version, installed,isUpdate)


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

    if args is None or len(args)==0:
        install_all(apps, installed,isUpdate)
        pass
    else:
        s = args[0].split('/')
        version = s[-1]
        s.pop(-1)

        download('/'.join(s), version, installed,isUpdate)
    rewrite(installed)

    print(f'{bc.OKBLUE}finished{bc.ENDC}')
