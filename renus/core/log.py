import os
from datetime import datetime

class Log:
    def __init__(self) -> None:
        self.filename='storage/logs/Renus-'+datetime.utcnow().strftime('%Y-%m-%d')+'.log'

    def info(self,msg):
        create(self.filename, msg, 'info')

    def warning(self,msg):
        create(self.filename, msg, 'warning')

    def error(self,msg):
        create(self.filename, msg, 'error')



def create(filename, value,typ):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'a') as output:
        output.write(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {typ.upper()}: {str(value)}\n")