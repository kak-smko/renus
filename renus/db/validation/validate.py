import copy

import renus.db.validation.rules as vr
from renus.response import abort_if
from renus.log import Log

def keys_exists(element, keys):
    """Resolve a nested value, creating missing keys along the path."""
    if not isinstance(element, dict):
        raise AttributeError('keys_exists() expects dict as first argument.')
    if len(keys) == 0:
        raise AttributeError('keys_exists() expects at least two arguments, one given.')

    _element = element
    for i,key in enumerate(keys):
        try:
            _element = _element[key]
        except KeyError:
            _element[key]=None if i==len(keys)-1 else {}
            if i<len(keys):
                _element =_element[key]

    return _element

def set_key(_res, keys,val):
    """Set a nested value, creating intermediate keys as needed."""
    for i,key in enumerate(keys):
        try:
            if i == len(keys) - 1:
                _res[key]=val
                _res = _res[key]
            else:
                _res = _res[key]
        except KeyError:
            _res[key]=val if i==len(keys)-1 else {}
            if i<len(keys):
                _res =_res[key]

class Validate:
    """Validate form data against a set of rules."""
    def __init__(self, form: dict, break_on_error: bool = False, log_on_error: bool = False) -> None:
        """Initialize the validator with the form to validate.

        Parameters
        ----------
        form:
            The input data to validate.
        break_on_error:
            Stop validating after the first error. Defaults to ``False``.
        log_on_error:
            Log errors when validation fails. Defaults to ``False``.
        """
        self._form = copy.deepcopy(form)
        self._break_on_error = break_on_error
        self._log_on_error = log_on_error
        self._error = False
        self._msg = {}

    def has_default(self, rules):
        """Return the first Default rule in the list, if any."""
        for item in rules:
            if isinstance(item, vr.Default):
                return item
        return False

    def has_convert(self, rules):
        """Return the first Convert rule in the list, if any."""
        for item in rules:
            if isinstance(item, vr.Convert):
                return item
        return False

    def has_required(self, rules):
        """Return whether a Required rule is present in the list."""
        for item in rules:
            if item is vr.Required or item == vr.Required:
                return True
        return False

    def rules(self, rules_data: dict, msg: str = 'invalid_data') -> dict:
        """Validate the form against rules and return the cleaned values."""
        res = {}
        for field in rules_data:
            keys=field.split('.')
            val = keys_exists(self._form, keys)
            default = self.has_default(rules_data[field])
            convert = self.has_convert(rules_data[field])
            if val is None and default is not False:
                val = default(val)
            if convert:
                val=convert(val)

            check = self.__check(val, rules_data[field])
            if check == True:
                set_key(res,keys,val)
            else:
                self._error = True
                self._msg[field] = check
                if self._break_on_error:
                    break
        if self._log_on_error:
            Log().error({'msg': msg, 'errors': self._msg})
        abort_if(self._error, {'msg': msg, 'errors': self._msg}, 422)

        return res

    def __check(self, input, rules):
        error = False
        msg = []
        for rule in rules:
            if rule != '$or' and not isinstance(rule, vr.Default) and not isinstance(rule, vr.Convert):
                test = rule(input)
                if test != True:
                    error = True
                    msg.append(test)
            elif rule == '$or':
                test = False
                for item in rules['$or']:
                    test = item(input)
                    if test == True:
                        break
                if test != True:
                    error = True
                    msg.append(test)

        return True if error == False else msg
