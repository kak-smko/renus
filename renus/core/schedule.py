import datetime
import functools
import threading
from traceback import format_exception

from renus.core.cache import Cache
from renus.core.log import Log


class Schedule:

    def __init__(self) -> None:
        self._interval = 1
        self._max_try=3
        self._timedelta = 210
        self._unit = None
        self._at_day = None
        self._at_hour = None
        self._at_minute = None
        self._at_secound = None
        self._forget_day = None
        self._forget_hour = None
        self._forget_minute = None
        self._forget_secound = None
        self._job_list = {}
        self._last_run = Cache().get('schedule_last_run',{})

    def timedelta(self, n):
        self._timedelta = n
        return self

    def every(self, n=1):
        self._interval = n
        self._max_try = 3
        self._unit = None
        self._at_day = None
        self._at_hour = None
        self._at_minute = None
        self._at_secound = None
        self._forget_day = None
        self._forget_hour = None
        self._forget_minute = None
        self._forget_secound = None
        return self

    def weeks(self):
        self._unit = 'weeks'
        return self

    def days(self):
        self._unit = 'days'
        return self

    def hours(self):
        self._unit = 'hours'
        return self

    def minutes(self):
        self._unit = 'minutes'
        return self

    def secounds(self):
        self._unit = 'secounds'
        return self

    def max_try(self,n:int):
        self._max_try = n
        return self

    def at(self, day:str=None, hour:int=None, minute:int=None, secound:int=None):
        self._at_day = day
        self._at_hour = hour
        self._at_minute = minute
        self._at_secound = secound
        return self

    def forget(self, days:list=None, hours:list=None, minutes:list=None, secounds:list=None):
        self._forget_day = days
        self._forget_hour = hours
        self._forget_minute = minutes
        self._forget_secound = secounds
        return self

    def do(self, key: str, func, *args, **kwargs):
        now = datetime.datetime.utcnow() + datetime.timedelta(minutes=self._timedelta)

        job_func = functools.partial(func, *args, **kwargs)
        try:
            functools.update_wrapper(job_func, func)
        except AttributeError:
            pass

        if self._unit == 'weeks':
            self.handle_weeks(key, job_func, now)
        elif self._unit == 'days':
            self.handle_days(key, job_func, now)
        elif self._unit == 'hours':
            self.handle_hours(key, job_func, now)
        elif self._unit == 'minutes':
            self.handle_minutes(key, job_func, now)
        elif self._unit == 'secounds':
            self.handle_secounds(key, job_func, now)

    def handle_weeks(self, key, job_func, now):
        d = now.strftime('%A')
        h = int(now.strftime('%H'))
        m = int(now.strftime('%M'))
        s = int(now.strftime('%S'))
        if (key in self._last_run and self._last_run[key] < now - datetime.timedelta(
                weeks=self._interval)) or key not in self._last_run:
            if self._at_day is not None and self._at_day != d:
                return None

            if self._at_hour is not None and self._at_hour != h:
                return None

            if self._at_minute is not None and self._at_minute != m:
                return None

            if self._at_secound is not None and self._at_secound != s:
                return None

            self._job_list[key] = job_func
    def handle_days(self, key, job_func, now):
        d = now.strftime('%A')
        h = int(now.strftime('%H'))
        m = int(now.strftime('%M'))
        s = int(now.strftime('%S'))
        if (key in self._last_run and self._last_run[key] < now - datetime.timedelta(
                days=self._interval)) or key not in self._last_run:
            if self._at_hour is not None and self._at_hour != h:
                return None

            if self._at_minute is not None and self._at_minute != m:
                return None

            if self._at_secound is not None and self._at_secound != s:
                return None

            if self._forget_day is not None and d in self._forget_day:
                return None

            self._job_list[key] = job_func

    def handle_hours(self, key, job_func, now):
        h = int(now.strftime('%H'))
        m = int(now.strftime('%M'))
        s = int(now.strftime('%S'))
        if (key in self._last_run and self._last_run[key] < now - datetime.timedelta(
                hours=self._interval)) or key not in self._last_run:

            if self._at_minute is not None and self._at_minute != m:
                return None

            if self._at_secound is not None and self._at_secound != s:
                return None

            if self._forget_hour is not None and h in self._forget_hour:
                return None

            self._job_list[key] = job_func

    def handle_minutes(self, key, job_func, now):
        m = int(now.strftime('%M'))
        s = int(now.strftime('%S'))
        if (key in self._last_run and self._last_run[key] < now - datetime.timedelta(
                minutes=self._interval)) or key not in self._last_run:

            if self._at_secound is not None and self._at_secound != s:
                return None

            if self._forget_minute is not None and m in self._forget_minute:
                return None

            self._job_list[key] = job_func

    def handle_secounds(self, key, job_func, now):
        s = int(now.strftime('%S'))
        if (key in self._last_run and self._last_run[key] < now - datetime.timedelta(
                seconds=self._interval)) or key not in self._last_run:

            if self._forget_secound is not None and s in self._forget_secound:
                return None

            self._job_list[key] = job_func

    def job(self,key, func,logged=False,multi=True,n=0):
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)
        self._last_run[key] = now
        Cache().put('schedule_last_run',self._last_run,24*60*60)
        try:
            if multi:
                run_threaded(func)
            else:
                func()
            if logged:
                Log().info(f'schedule job {key} at: {str(now)}')
            self._job_list.pop(key)
        except Exception as exc:
            if n < self._max_try:
                self.job(key,func,logged,multi,n=n+1)
            else:
                Log().error(f'schedule failed [{key}] at: {str(now)} - {str(exc)}')
                self._job_list.pop(key)

    def run(self,logged=False, multi=True):
        jobs = self._job_list.copy()
        for key, func in jobs.items():
            self.job(key,func,logged,multi)

def thread_exception_handler(exc):
   Log().error(f'schedule failed at: '
                f'{str(exc[1])} - '
                f'{format_exception(exc[0],exc[1],exc[2])}'
               )

def run_threaded(job_func):
    threading.excepthook = thread_exception_handler
    t = threading.Thread(target=job_func)
    t.start()

