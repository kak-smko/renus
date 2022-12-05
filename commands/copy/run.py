import os
import zipfile

exclude_all = [
    '__pycache__',
    'frontend',
    '.idea',
    '.git',
    '.github'
]
exclude = [
    'storage/cache',
    'storage/logs'
]

exclude_ext = [
    '.vue',
    '.js'
    '.css'
    '.scss'
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
            if not dirname.startswith('public'):
                has = False
                for ext in exclude_ext:
                    if file.endswith(ext):
                        has = True
                        break
                if has:
                    continue
            ziph.write(os.path.join(dirname, file))

def folders():
    res=[]
    for entry in os.scandir('./'):
        if entry.is_dir():
            res.append(entry.name)

    return res

def run():
    path = input('copy folder path:<D:/projects/uploads>').lower()
    if path =='':
        path='D:/projects/uploads'

    ff=folders()

    app_name = input('copy name:')
    print(f'start copy {app_name}...')
    if not os.path.exists(f'{path}'):
        os.makedirs(f'{path}')
    zipf = zipfile.ZipFile(f'{path}/{app_name}.zip', 'w', zipfile.ZIP_DEFLATED)
    for folder in ff:
        if folder not in exclude_all:
            zipdir(f'{folder}/', zipf)

    zipf.write('index.py')
    zipf.close()

    print('end')

