from renus.core.routing import Router
import routes.index
from extension.renus.permission.middleware import PermissionMiddleware
from extension.renus.permission.model import Permission

def run():
    all=Router().all
    names=set()
    names.add('delete_storage')
    for a in all:
        for method in all[a]:
            for route in all[a][method]:
                for md in route['middlewares']:
                    if isinstance(md,PermissionMiddleware):
                        print(route['path'], md.names)
                        for name in md.names:
                            names.add(name)

    for name in names:
        Permission('').where({
            'name':name
        }).update({},True)

    print('done')