import os
import zipfile
from datetime import datetime

exclude_all = [
    '__pycache__',
    'node_modules',
    '.idea',
    '.git',
    '.github'
]
exclude = [
    'venv',
    'storage/cache',
    'storage/logs'
]


def zipdir(path, ziph):
    for dirname, subdirs, files in os.walk(path):
        has=False
        for dir in exclude_all:
            if dirname.find(dir)!=-1:
                has=True
                break
        for dir in exclude:
            if dirname.startswith(dir):
                has = True
                break
        if has:
            continue
        ziph.write(dirname)
        for file in files:
            ziph.write(os.path.join(dirname, file))

def folders():
    res=[]
    for entry in os.scandir('./'):
        if entry.is_dir():
            res.append(entry.name)

    return res

def run():
    path = input('backups folder path:<D:/projects/backups>').lower()
    if path =='':
        path='D:/projects/backups'

    ff=folders()
    date = str(datetime.utcnow().date())
    app_name = input('backup name:')
    print(f'start backing up {app_name}...')
    if not os.path.exists(f'{path}/{app_name}'):
        os.makedirs(f'{path}/{app_name}')
    zipf = zipfile.ZipFile(f'{path}/{app_name}/{app_name}_{date}.zip', 'w', zipfile.ZIP_DEFLATED)
    for folder in ff:
        if folder not in exclude_all:
            zipdir(f'{folder}/', zipf)

    zipf.write('index.py')
    zipf.close()

    print('end')

