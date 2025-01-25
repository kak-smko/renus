import os


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


def _add_admin_templates(install):
    with open('./frontend/admin/src/router/index.js', 'r') as file:
        all = file.read()
        for item in install.admin_templates:
            all = all.replace('/* {{place new import}} */',
                              '/* {{place new import}} */\nconst ' + item.get('name',
                                                                              'test') + ' = () => import("' + item.get(
                                  'file', 'test') + '");')
            all = all.replace('/* {{place new Route}} */',
                              '/* {{place new Route}} */\n' + item.get('path', '{}') + ',')

        with open('./frontend/admin/src/router/index.js', 'w') as b:
            b.write(all)


def _add_index_templates(install):
    with open('./frontend/index/src/router/index.js', 'r') as file:
        all = file.read()
        for item in install.index_templates:
            all = all.replace('/* {{place new import}} */',
                              '/* {{place new import}} */\nconst ' + item.get('name',
                                                                              'test') + ' = () => import("' + item.get(
                                  'file', 'test') + '");')
            all = all.replace('/* {{place new Route home}} */',
                              '/* {{place new Route home}} */\n' + item.get('path', '') + ',')
        with open('./frontend/index/src/router/index.js', 'w') as b:
            b.write(all)


def _add_user_templates(install):
    with open('./frontend/index/src/router/index.js', 'r') as file:
        all = file.read()
        for item in install.user_templates:
            all = all.replace('/* {{place new import}} */',
                              '/* {{place new import}} */\nconst ' + item.get('name',
                                                                              'test') + ' = () => import("' + item.get(
                                  'file', 'test') + '");')
            all = all.replace('/* {{place new Route user}} */',
                              '/* {{place new Route user}} */\n' + item.get('path', '') + ',')
        with open('./frontend/index/src/router/index.js', 'w') as b:
            b.write(all)


def _add_config(install):
    if install.config:
        with open(f'./config/{install.config[0]}.py', 'w') as b:
            b.write(open(install.config[1], 'r').read())
