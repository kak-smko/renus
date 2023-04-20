import traceback
import json

from renus.core.serialize import jsonEncoder
from renus.core.status import Status
from renus.core.log import Log


def abort(msg, status_code: Status = Status.HTTP_400_BAD_REQUEST):
    if type(msg).__name__=='str':
        msg={'msg':msg}
    raise RuntimeError(msg, status_code)


def abort_if(condition: bool, msg, status_code: Status = Status.HTTP_400_BAD_REQUEST):
    if condition:
        if type(msg).__name__ == 'str':
            msg = {'msg': msg}
        raise RuntimeError(msg, status_code)


def abort_unless(condition: bool, msg, status_code: Status = Status.HTTP_400_BAD_REQUEST):
    if not condition:
        if type(msg).__name__ == 'str':
            msg = {'msg': msg}
        raise RuntimeError(msg, status_code)


def debug_response(exc: Exception,debug=False):
    if type(exc).__name__=='RuntimeError' and type(exc.args[0]).__name__=='dict' and len(exc.args)==2 and 'msg' in exc.args[0]:
        return exc.args[0],exc.args[1]

    status_code = Status.HTTP_500_INTERNAL_SERVER_ERROR
    traceback_obj = traceback.TracebackException.from_exception(
        exc, capture_locals=True
    )

    error = f"{traceback_obj.exc_type.__name__}: {str(traceback_obj)}"
    stacks = traceback_obj.stack.format()
    stack_list = []
    for stack in stacks:
        stack_list.append(stack.split('\n'))

    res = {
        'msg': error,
        'file': traceback.format_tb(exc.__traceback__),
        'stack': stack_list,
    }
    Log().error(json.dumps(
        res,
        ensure_ascii=False,
        allow_nan=True,
        indent=4,
        separators=(",", ":"),
        cls=jsonEncoder
    ))
    if not debug:
        return {
                   'msg': 'Internal Server Error',
               }, status_code
    traceback.print_tb(exc.__traceback__)
    return res, status_code
