import json

from renus.core.routing import Router
from renus.util.helper import hash_new_password


def run(args):
    if args[0] == 'setting':
        from app.extension.renus.setting.model import Setting
        with open('extension/renus/setting/db.json','r') as db:
            d=json.loads(db.read())
            for item in d:
                Setting('').where({
                    'name':item['name']
                }).update(item, True)
        print('DB Settings Created.')

    if args[0] == 'translate':
        from app.extension.renus.translate.model import Translate
        with open('extension/renus/translate/db.json','r') as db:
            d=json.loads(db.read())
            for item in d:
                Translate('').where({
                    'key':item['key']
                }).update(item, True)
        print('DB Translates Created.')

    if args[0]=='super_admin':
        from app.extension.renus.role.model import Role
        from app.extension.renus.permission.model import Permission
        from app.extension.renus.user.model import User
        country_code = int(input('country_code: '))
        phone = int(input('phone: '))
        name = input('name: ')
        Permission('').where({
            'name': '*'
        }).update({}, True)
        permissions = Permission('').where({
            'name': '*'
        }).select('_id').get(False)
        res = []
        for p in permissions:
            res.append(p['_id'])
        Role('').where({
            'name': 'super_admin'
        }).update({'permission_ids': res,'active':True}, True)

        User('').where({
            'country_code': str(country_code),
            'phone': str(phone)
        }).update({
            'name': name,
            'username': 'admin',
            'password':hash_new_password('admin')
        }, True)
        User('').where({
            'country_code': str(country_code),
            'phone': str(phone)
        }).sync_roles(['super_admin'])
        print('Super Admin Created.\nPlease Change username and password.\nusername=admin\npassword=admin')