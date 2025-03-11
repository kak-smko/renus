import os
import shutil


def _add_cls(install, app):
    if install.cls:
        os.makedirs('./app/extension/' + app, exist_ok=True)
        for item in install.cls:
            with open(f'./app/extension/{app}/{item[0]}.py', 'a') as file:
                f = ''
                f += f'from {item[1]} import {item[2]}\n\n'
                f += f'class {item[3]}({item[2]}):\n'
                f += '    pass\n'
                file.write(f)


def _add_imprt(install, app):
    if install.imprt:
        os.makedirs('./app/extension/' + app, exist_ok=True)
        for item in install.imprt:
            with open(f'./app/extension/{app}/{item[0]}.py', 'a') as file:
                f = f'from {item[1]} import {item[2]}\n'
                file.write(f)


def _add_route(install, app):
    if install.route:
        os.makedirs('./app/extension/' + app, exist_ok=True)
        with open(f'./app/extension/{app}/route.py', 'w') as file:
            f = 'import ' + install.route + '\n'
            file.write(f)

        with open('./routes/index.py', 'r') as file:
            all = file.read()
            routes = 'import ' + f'app.extension.{app.replace("/", ".")}.route' + '\n'
            all = routes + all
            with open('./routes/index.py', 'w') as b:
                b.write(all)


def _remove_route(install, app):
    if install.route:
        with open('./routes/index.py', 'r') as file:
            all = file.read()
            routes = 'import ' + f'app.extension.{app.replace("/", ".")}.route' + '\n'
            all = all.replace(routes, '')
            with open('./routes/index.py', 'w') as b:
                b.write(all)


def _add_admin_templates(install, app):
    name = app.replace("/", "_")
    shutil.copytree(install.admin_templates, './frontend/admin/src/extension/' + app)
    with open('./frontend/admin/src/router/index.js', 'r') as file:
        all = file.read()
        all = "import " + name + "_routes from '@/extension/" + app + "/route.js'\n" + all
        all = all.replace('/* {{place new Route}} */',
                          '/* {{place new Route}} */\n...' + name + '_routes,')

        with open('./frontend/admin/src/router/index.js', 'w') as b:
            b.write(all)


def _remove_admin_templates(app):
    name = app.replace("/", "_")
    shutil.rmtree('./frontend/admin/src/extension/' + app)
    with open('./frontend/admin/src/router/index.js', 'r') as file:
        all = file.read()
        all = all.replace("import " + name + "_routes from '@/extension/" + app + "/route.js'\n", '')
        all = all.replace('...' + name + '_routes,', '')

        with open('./frontend/admin/src/router/index.js', 'w') as b:
            b.write(all)


def _add_index_templates(install, app):
    name = app.replace("/", "_")
    shutil.copytree(install.index_templates, './frontend/index/src/extension/' + app)
    with open('./frontend/index/src/router/index.js', 'r') as file:
        all = file.read()
        all = "import " + name + "_routes from '@/extension/" + app + "/route.js'\n" + all

        all = all.replace('/* {{place new Route}} */',
                          '/* {{place new Route}} */\n...' + name + '_routes,')

        with open('./frontend/index/src/router/index.js', 'w') as b:
            b.write(all)


def _remove_index_templates(app):
    name = app.replace("/", "_")
    shutil.rmtree('./frontend/index/src/extension/' + app)
    with open('./frontend/index/src/router/index.js', 'r') as file:
        all = file.read()
        all = all.replace("import " + name + "_routes from '@/extension/" + app + "/route.js'\n", '')
        all = all.replace('...' + name + '_routes,', '')

        with open('./frontend/index/src/router/index.js', 'w') as b:
            b.write(all)


def _add_component_templates(install, app):
    shutil.copytree(install.component_templates, './frontend/index/src/components/' + app)
    shutil.copytree(install.component_templates, './frontend/admin/src/components/' + app)


def _remove_component_templates(app):
    shutil.rmtree('./frontend/index/src/components/' + app)
    shutil.rmtree('./frontend/admin/src/components/' + app)


def _add_config(install):
    if install.config:
        with open(f'./config/{install.config[0]}.py', 'w') as b:
            b.write(open(install.config[1], 'r').read())


def _remove_config(install):
    if install.config:
        os.remove(f'./config/{install.config[0]}.py')
