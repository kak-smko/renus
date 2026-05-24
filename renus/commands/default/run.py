import re
import secrets

from renus.util.helper import hash_new_password


def run(args):

    if args[0]=='super_admin':
        from app.extension.codenus.role.model import Role
        from app.extension.codenus.permission.model import Permission
        from app.extension.codenus.user.model import User
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
            'phone': str(country_code)+' '+str(phone)
        }).update({
            'name': name,
            'username': 'admin',
            'password':hash_new_password('admin')
        }, True)
        User('').where({
            'phone': str(country_code)+' '+str(phone)
        }).sync_roles(['super_admin'])
        print('Super Admin Created.\nPlease Change username and password.\nusername=admin\npassword=admin')
    elif args[0] == 'encrypt':
        from extension.codenus.user.crypt import Crypto
        with open("config/app.py", "r", encoding="utf-8") as f:
            content = f.read()

        new_private, new_public = Crypto().generate_server_keys()
        new_private = new_private.replace(b"\n", b"").decode()
        new_public = new_public.replace(b"\n", b"").decode()
        new_key = secrets.token_hex(16)

        replacements = {
            'key': new_key,
            'public_key': new_public,
            'private_key': new_private,
        }

        for name, value in replacements.items():
            pattern = rf'^({name})\s*=\s*b".*"$'
            content = re.sub(pattern, f'\\1 = b"{value}"', content, flags=re.MULTILINE)

        with open("config/app.py", "w", encoding="utf-8") as f:
            f.write(content)

        for name in ["index", "admin"]:
            with open(f"frontend/{name}/.env", "r", encoding="utf-8") as f:
                content = f.read()

            content = re.sub(rf'^(VITE_APP_SERVER_PUBKEY)\s*=\s*.*$', f'\\1={new_public}', content, flags=re.MULTILINE)

            with open(f"frontend/{name}/.env", "w", encoding="utf-8") as f:
                f.write(content)
