import os
import pkg_resources

controller_temp = pkg_resources.resource_filename('renus', './commands/app/controller.temp')
model_temp = pkg_resources.resource_filename('renus', './commands/app/model.temp')
vue_temp = pkg_resources.resource_filename('renus', './commands/app/vue.temp')
route_temp = pkg_resources.resource_filename('renus', './commands/app/route.temp')

def to_camel_case(snake_str):
    components = snake_str.split('_')
    return ''.join(x.title() for x in components)


def add_temp(name,names, name_camel, name_db,folder:list):
    pth = 'app/'
    pname = ''
    vname = ''
    if len(folder) > 0:
        pth += '/'.join(folder) + '/'
        pname = '.'.join(folder) + '.'
        vname = '/'+'/'.join(folder)+'/'
    pth += name + '/'
    with open(controller_temp,'r') as file:
        os.makedirs(pth,exist_ok=True)
        all=file.read()
        all=all.replace('{name}',pname+name)
        all=all.replace('{name_camel}',name_camel)
        with open(pth+'controller.py','w') as controller:
            controller.write(all)

    with open(model_temp,'r') as file:
        all=file.read()
        all=all.replace('{name_camel}',name_camel)
        all=all.replace('{name_db}',name_db)
        with open(pth+'model.py','w') as controller:
            controller.write(all)

    with open(vue_temp,'r') as file:
        os.makedirs('./frontend/src/views/admin/'+vname.lstrip('/'), exist_ok=True)
        all=file.read()
        all=all.replace('{name}',name)
        all=all.replace('{names}',names)
        all = all.replace('{folder}', vname.lstrip('/'))
        with open('./frontend/src/views/admin/'+vname.lstrip('/')+name+'.vue','w') as controller:
            controller.write(all)

    with open(route_temp,'r') as file:
        all=file.read()
        all=all.replace('{name}',pname+name)
        all=all.replace('{names}',names)
        all = all.replace('{name_camel}', name_camel)
        all = all.replace('{folder}', vname.rstrip('/'))
        with open(pth+'route.py','w') as controller:
            controller.write(all)

def to_plural(word):
    slice = list(word)
    if slice[-1] == 'y':
        slice.remove('y')
        slice.append('ies')

    elif slice[- 1] == 'f':
        slice.remove('f')
        slice.append('ves')

    elif slice[- 2:] == ['f','e']:
        slice.remove('fe')
        slice.append('ves')

    elif slice[- 1] == 's' or slice[-1] == 'x' or slice[-1] == 'z' or slice[- 2:] == ['c','h'] or slice[- 2:] == ['s','h']:
        slice.append('es')

    elif slice[- 2:] == ['u','s']:
        slice.remove('us')
        slice.append('i')

    else:
        slice.append('s')

    return ''.join(slice)


def add_routes(name, names, name_camel,folder):
    pname = ''
    vname = ''
    if len(folder) > 0:
        pname = '.'.join(folder) + '.'
        vname = '/'.join(folder) + '/'

    with open('./routes/index.py', 'r') as file:
        all=file.read()
        all=f'import app.{pname+name}.route\n'+all

        with open('./routes/index.py', 'w') as b:
                b.write(all)

    with open('./frontend/src/router/admin.js', 'r') as file:
        all=file.read()
        all=all.replace('/* {{place new import}} */','/* {{place new import}} */\nconst '+names+' = () => import("../views/admin/'+vname+name+'");')
        all=all.replace('/* {{place new Route}} */','/* {{place new Route}} */\n{ path: "'+vname+names+'", name: "'+names+'", component: '+names+' },')

        with open('./frontend/src/router/admin.js', 'w') as b:
                b.write(all)


def run():
    name = input('name (single lowercase):').lower()
    folder=name.split('.')
    name=folder[-1]
    folder=folder[:-1]
    name_camel = to_camel_case(name)
    names = to_plural(to_camel_case(name))
    names = names[0].lower() + names[1:]
    name_db = name.replace('_', '-')

    add_temp(name, names, name_camel, name_db,folder)
    print('templates created.')
    add_routes(name, names, name_camel,folder)
    print('routes created.')
    print(f'{name} is done.')
