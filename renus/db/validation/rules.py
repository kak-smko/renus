from datetime import date, datetime
import os
import re

class Default:
    """Provide a default value when the input is ``None``."""
    def __init__(self, data):
        """Store the default value to apply.

        Parameters
        ----------
        data:
            The default value, or a callable producing it.
        """
        self.d = data

    def __call__(self, input):
        if input is None:
            if callable(self.d) and not isinstance(self.d, type):
                return self.d()
            return self.d
        return True

class Convert:
    """Convert the input value before further validation."""
    def __init__(self, func=None, inputs: list = None):
        """Configure the conversion rule.

        Parameters
        ----------
        func:
            Callable or type used to convert the value. Defaults to ``None``.
        inputs:
            Optional mapping of input-to-output pairs. Defaults to ``None``.
        """
        self.func = func
        self.inputs = inputs

    def __call__(self, input):
        if input is None:
            return None
        if self.inputs is not None:
            for i in self.inputs:
                if i[0] == input:
                    return i[1]
            return input
        if self.func is not None:
            if isinstance(self.func, type) and isinstance(input, self.func):
                return input
            if self.func is datetime and isinstance(input, str):
                return datetime.fromisoformat(input)
            if self.func is date and isinstance(input, str):
                return date.fromisoformat(input)
            return self.func(input)
        return input

def Required(input) -> any:
    """Pass when the input is not ``None``."""
    if input is not None:
        return True
    return 'required_error'

def String(input) -> any:
    """Pass when the input is a string."""
    if input is None:
        return True
    t = type(input)
    if t is str:
        return True
    return ['type_error', ['string', str(t)]]

def Bool(input) -> any:
    """Pass when the input is a boolean."""
    if input is None:
        return True
    t = type(input)
    if t is bool:
        return True
    return ['type_error', ['bool', str(t)]]

def List(input) -> any:
    """Pass when the input is a list."""
    if input is None:
        return True
    t = type(input)
    if t is list:
        return True
    return ['type_error', ['list', str(t)]]

def Dict(input) -> any:
    """Pass when the input is a dict."""
    if input is None:
        return True
    t = type(input)
    if t is dict:
        return True
    return ['type_error', ['dict', str(t)]]

def Int(input) -> any:
    """Pass when the input is an integer."""
    if input is None:
        return True
    t = type(input)
    if t is int:
        return True
    return ['type_error', ['int', str(t)]]

def Float(input) -> any:
    """Pass when the input is a float or integer."""
    if input is None:
        return True
    t = type(input)
    if t is float or t is int:
        return True

    return ['type_error', ['float', str(t)]]

class Len:
    """Pass when the input length equals a given value."""
    def __init__(self, length: int):
        """Set the expected length.

        Parameters
        ----------
        length:
            The required length of the input.
        """
        self.l = length

    def __call__(self, input):
        if input is None:
            return True
        try:
            length = len(input)
            if length == self.l:
                return True
            return ['len_error', [self.l, length]]
        except Exception as e:
            return ['len_error', [self.l, 'type_error']]

class MinLen:
    """Pass when the input length is at least a given value."""
    def __init__(self, length: int):
        """Set the minimum length.

        Parameters
        ----------
        length:
            The minimum allowed length of the input.
        """
        self.l = length

    def __call__(self, input):
        if input is None:
            return True
        try:
            length = len(input)
            if length >= self.l:
                return True
            return ['min_len_error', [self.l, length]]
        except Exception as e:
            return ['min_len_error', [self.l, 'type_error']]

class MaxLen:
    """Pass when the input length is at most a given value."""
    def __init__(self, length: int):
        """Set the maximum length.

        Parameters
        ----------
        length:
            The maximum allowed length of the input.
        """
        self.l = length

    def __call__(self, input):
        if input is None:
            return True
        try:
            length = len(input)
            if length <= self.l:
                return True
            return ['max_len_error', [self.l, length]]
        except Exception as e:
            return ['max_len_error', [self.l, 'type_error']]

class Eq:
    """Pass when the input equals a given value."""
    def __init__(self, length: float):
        """Set the expected value.

        Parameters
        ----------
        length:
            The value the input must equal.
        """
        self.l = length

    def __call__(self, input):
        if input is None:
            return True

        if input == self.l:
            return True
        return ['eq_error', [self.l, input]]

class Min:
    """Pass when the input is at least a given value."""
    def __init__(self, length: float):
        """Set the minimum value.

        Parameters
        ----------
        length:
            The minimum allowed value of the input.
        """
        self.l = length

    def __call__(self, input):
        if input is None:
            return True

        if input >= self.l:
            return True
        return ['min_error', [self.l, input]]

class Max:
    """Pass when the input is at most a given value."""
    def __init__(self, length: float):
        """Set the maximum value.

        Parameters
        ----------
        length:
            The maximum allowed value of the input.
        """
        self.l = length

    def __call__(self, input):
        if input is None:
            return True

        if input <= self.l:
            return True
        return ['max_error', [self.l, input]]

def Numeric(input) -> any:
    """Pass when the input contains only digits."""
    if input is None:
        return True
    if re.compile(r'[\d]+').fullmatch(str(input)) != None:
        return True
    return ['numeric_error', [input]]

def Accepted(input) -> any:
    """Pass for common affirmative values such as yes, on, or 1."""
    if input is None:
        return True
    if String(input) == True:
        input = input.lower()
    acceptable = ['yes', 'on', '1', 1, True, 'true']
    if input in acceptable:
        return True
    return ['accepted_error', [input]]

class Email:
    """Pass when the input is a valid email address."""
    def __init__(self, allow_domain: list = None):
        """Configure the email rule.

        Parameters
        ----------
        allow_domain:
            Optional list of permitted domains. Defaults to ``None``.
        """
        self.allow_domain = [] if allow_domain is None else allow_domain

    def __call__(self, input):

        if input is None:
            return True

        is_string = String(input)
        if is_string == True:
            input = input.lower()
        else:
            return is_string

        parse = input.split('@')
        if len(parse) < 2:
            return ['email_at_error', [input]]
        name, domain = parse
        parse_domain = domain.split('.')
        if len(parse_domain) < 2:
            return ['email_domain_name_error', [domain]]
        if len(parse_domain[1]) < 2:
            return ['email_domain_name_error', [domain]]
        if isinstance(self.allow_domain, (list, tuple, set)) and len(self.allow_domain) > 0:
            if domain not in self.allow_domain and not any(
                domain.endswith("." + str(d)) or domain == str(d) for d in self.allow_domain
            ):
                return ['email_domain_allow_error', [domain, str(self.allow_domain)]]
        if len(name) < 1:
            return ['email_name_error', [1, input]]

        return True

class In:
    """Pass when the input is in the allowed set of values."""
    def __init__(self, *vars):
        """Set the allowed values.

        Parameters
        ----------
        vars:
            Values the input is allowed to take.
        """
        self.vars = list(vars)

    def __call__(self, input):
        if input is None:
            return True
        if input in self.vars:
            return True
        return ['in_error', [input, str(self.vars)]]

class NotIn:
    """Pass when the input is not in the forbidden set of values."""
    def __init__(self, *vars):
        """Set the forbidden values.

        Parameters
        ----------
        vars:
            Values the input must not take.
        """
        self.vars = list(vars)

    def __call__(self, input):
        if input is None:
            return True

        if input not in self.vars:
            return True
        return ['not_in_error', [input, str(self.vars)]]

class Regex:
    """Pass when the input matches a regular expression."""
    def __init__(self, rule: str, msg: str = None):
        """Configure the regex rule.

        Parameters
        ----------
        rule:
            The regular expression pattern to match.
        msg:
            Optional custom error message. Defaults to ``None``.
        """
        self.rule = rule
        self.msg = msg

    def __call__(self, input):
        if input is None:
            return True
        msg = None

        if re.compile(self.rule).fullmatch(input) is not None:
            return True
        return ['regex_error', [input, msg]]

def Url(input):
    """Pass when the input is a valid URL."""
    if input is None:
        return True
    string = String(input)
    if string is not True:
        return string
    pattern = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"

    if re.compile(pattern).fullmatch(input) is not None:
        return True
    return ['url_error', [input]]

def Ip(input):
    """Pass when the input is a valid IPv4 address."""
    if input is None:
        return True
    string = String(input)
    if string is not True:
        return string
    ipv = re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", input)
    if bool(ipv) and all(map(lambda n: 0 <= int(n) <= 255, ipv.groups())):
        return True

    return ['ip_error', [input]]

class Extension:
    """Pass when the input has an allowed file extension."""
    def __init__(self, extensions: list = None):
        """Set the allowed extensions.

        Parameters
        ----------
        extensions:
            List of allowed file extensions. Defaults to a common image set.
        """
        self.allowed = ['jpeg', 'jpg', 'png', 'gif', 'svg', 'webp'] if extensions is None else extensions

    def __call__(self, input):
        if input is None:
            return True
        string = String(input)
        if string is True:
            return self.__check(input)

        for img in input:
            c = self.__check(img)
            if c is not True:
                return c
        return True

    def __check(self, string):
        i = string.split('.')
        if i[-1] not in self.allowed:
            return ['extension_error', [string]]
        return True

class Unique:
    """Pass when the field value is unique on the model."""
    def __init__(self, model, field, current_id=None):
        """Configure the unique rule.

        Parameters
        ----------
        model:
            The model to query for existing values.
        field:
            The field name checked for uniqueness.
        current_id:
            Optional id to exclude when checking. Defaults to ``None``.
        """
        self.model = model
        self.field = field
        self.current_id = current_id

    def __call__(self, input):

        if input is None:
            return True

        model = self.model.where({
            self.field: input
        }).select('_id').first()
        if model is None:
            return True

        if self.current_id is not None and str(self.current_id) == str(model['_id']):
            return True
        return ['unique_error', [input]]

class Exists:
    """Pass when the field value exists on the model."""
    def __init__(self, model, field):
        """Configure the exists rule.

        Parameters
        ----------
        model:
            The model to query for existing values.
        field:
            The field name checked for existence.
        """
        self.model = model
        self.field = field

    def __call__(self, input):

        if input is None:
            return True

        model = self.model.where({
            self.field: input
        }).select('_id').first()
        if model is not None:
            return True
        return ['exists_error', [input]]

class ExistsCount:
    """Pass when matching record counts satisfy the configured bounds."""
    def __init__(self, model, field, count: int = None, minCount: int = None, maxCount: int = None):
        """Configure the existence-count constraints.

        Parameters
        ----------
        model:
            The model to query for matching records.
        field:
            The field name checked for matches.
        count:
            Optional exact expected count. Defaults to ``None``.
        minCount:
            Optional minimum allowed count. Defaults to ``None``.
        maxCount:
            Optional maximum allowed count. Defaults to ``None``.
        """
        self.model = model
        self.field = field
        self.count = count
        self.minCount = minCount
        self.maxCount = maxCount

    def __call__(self, input):
        if input is None:
            return True

        count = self.model.where({
            self.field: input
        }).select('_id').count()

        if (self.count is not None and self.count == count) or (
                self.minCount is not None and self.minCount <= count) or (
                self.maxCount is not None and self.maxCount >= count):
            return True
        return ['exists_count_error', [input]]

class FileSize:
    """Pass when file sizes fall within the allowed byte range."""
    def __init__(self, max_byte: int = 0, min_byte: int = 0, replace: list = None, item_dict: str = None):
        """Configure the file size constraints.

        Parameters
        ----------
        max_byte:
            Maximum allowed file size. Defaults to ``0`` (no limit).
        min_byte:
            Minimum allowed file size. Defaults to ``0`` (no limit).
        replace:
            Optional path replacement rules. Defaults to ``None``.
        item_dict:
            Optional dict key holding the file link. Defaults to ``None``.
        """
        if replace is None:
            replace = [('storage/img/', 'storage/'), ('storage/', 'storage/public/')]
        self.maxByte = max_byte
        self.minByte = min_byte
        self.replace = replace
        self.item_dict = item_dict

    def __call__(self, input):
        if input is None:
            return True
        t = type(input)
        if t is str:
            input = [input]
        passed = True
        if self.maxByte:
            for item in input:
                tt = type(item)
                if tt is dict:
                    link = item[self.item_dict]
                else:
                    link = item
                for rep in self.replace:
                    link = link.replace(rep[0], rep[1])
                state = os.stat(link)
                if state.st_size <= self.maxByte:
                    continue
                passed = ['max_file_size_error', [item, state.st_size, self.maxByte]]
        if self.minByte:
            for item in input:
                tt = type(item)
                if tt is dict:
                    link = item[self.item_dict]
                else:
                    link = item
                for rep in self.replace:
                    link = link.replace(rep[0], rep[1])
                state = os.stat(link)
                if state.st_size >= self.minByte:
                    continue
                passed = ['min_file_size_error', [item, state.st_size, self.minByte]]

        return passed

class Schema:
    """Validate a dict against a schema of nested rules."""

    def __init__(self, schema: dict, strict: bool = True):
        """Configure the schema rule.

        Parameters
        ----------
        schema:
            Mapping of fields to their validation rules.
        strict:
            Reject extra fields. Defaults to ``True``.
        """
        self.schema = schema
        self.strict = strict

    def __call__(self, input):
        if input is None:
            return True

        if not isinstance(input, dict):
            return ['type_error', ['dict', str(type(input))]]

        if self.strict:
            extra_fields = set(input.keys()) - set(self.schema.keys())
            if extra_fields:
                return ['schema_strict_error', [list(extra_fields)]]

        from renus.db.validation.validate import Validate
        input.update(Validate(input).rules(self.schema))

        return True

class Each:
    """Apply a set of rules to every item of a collection."""

    def __init__(self, *rules):
        """Set the rules applied to each item.

        Parameters
        ----------
        rules:
            Rules to run against every collection item.
        """
        self.rules = rules

    def __call__(self, input):
        if input is None:
            return True

        if not isinstance(input, list) and not isinstance(input, dict):
            return ['type_error', ['list|dict', str(type(input))]]

        if isinstance(input, list):
            d=enumerate(input)
        else:
            d=input.items()
        errors = {}
        for index, item in d:
            item_errors = []
            for rule in self.rules:
                result = rule(item)
                if result is not True:
                    item_errors.append(result)
            if item_errors:
                errors[str(index)] = item_errors

        if errors:
            return ['each_error', [errors]]
        return True

class MaxDepth:
    """Pass when nested input stays within a maximum depth."""

    def __init__(self, max_depth: int ):
        """Set the maximum nesting depth.

        Parameters
        ----------
        max_depth:
            The maximum allowed nesting depth.
        """
        self.max_depth = max_depth

    def __call__(self, input):
        if input is None:
            return True

        depth = self._calculate_depth(input)
        if depth > self.max_depth:
            return ['max_depth_error', [self.max_depth, depth]]
        return True

    def _calculate_depth(self, obj, current_depth=0):
        if current_depth > self.max_depth:
            return current_depth

        if isinstance(obj, dict):
            if not obj:
                return current_depth
            return max(self._calculate_depth(v, current_depth + 1) for v in obj.values())
        elif isinstance(obj, list):
            if not obj:
                return current_depth
            return max(self._calculate_depth(item, current_depth + 1) for item in obj)
        return current_depth

class Or:
    """Pass when at least one of the given rules passes."""

    def __init__(self, *rules):
        """Set the rules to try.

        Parameters
        ----------
        rules:
            Rules of which at least one must pass.
        """
        self.rules = rules

    def __call__(self, input):
        if input is None:
            return True

        errors = []
        for rule in self.rules:
            result = rule(input)
            if result is True:
                return True
            errors.append(result)

        return ['or_error', [errors]]

class And:
    """Pass when all of the given rules pass."""

    def __init__(self, *rules):
        """Set the rules that must all pass.

        Parameters
        ----------
        rules:
            Rules of which every one must pass.
        """
        self.rules = rules

    def __call__(self, input):
        if input is None:
            return True

        errors = []
        for rule in self.rules:
            result = rule(input)
            if result is not True:
                errors.append(result)
        if len(errors) == 0:
            return True

        return ['and_error', [errors]]
