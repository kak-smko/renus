import os
import re

from renus.db.validation.base import Rule

class Required(Rule):
    """Pass when the input is not ``None``."""

    is_required = True

    def __call__(self, input) -> any:
        return True if input is not None else "required_error"

    def json_schema(self) -> dict[str, any]:
        return {}
        
class String(Rule):
    """Pass when the input is a string."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if type(input) is str:
            return True
        return ['type_error', ['string', str(type(input))]]

    def json_schema(self):
        return {"type": "string"}


class Bool(Rule):
    """Pass when the input is a boolean."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if type(input) is bool:
            return True
        return ['type_error', ['bool', str(type(input))]]

    def json_schema(self):
        return {"type": "boolean"}


class List(Rule):
    """Pass when the input is a list."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if type(input) is list:
            return True
        return ['type_error', ['list', str(type(input))]]

    def json_schema(self):
        return {"type": "array"}


class Dict(Rule):
    """Pass when the input is a dict."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if type(input) is dict:
            return True
        return ['type_error', ['dict', str(type(input))]]

    def json_schema(self):
        return {"type": "object"}


class Int(Rule):
    """Pass when the input is an integer."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if type(input) is int:
            return True
        return ['type_error', ['int', str(type(input))]]

    def json_schema(self):
        return {"type": "integer"}


class Float(Rule):
    """Pass when the input is a float or integer."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if type(input) in (float, int):
            return True
        return ['type_error', ['float', str(type(input))]]

    def json_schema(self):
        return {"type": "number"}

class Len(Rule):
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

    def json_schema(self):
        return {"minLength": self.l, "maxLength": self.l}

class MinLen(Rule):
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

    def json_schema(self):
        return {"minLength": self.l}

class MaxLen(Rule):
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

    def json_schema(self):
        return {"maxLength": self.l}

class Eq(Rule):
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

    def json_schema(self):
        return {"const": self.l}

class Min(Rule):
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

    def json_schema(self):
        return {"minimum": self.l}

class Max(Rule):
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

    def json_schema(self):
        return {"maximum": self.l}

class Numeric(Rule):
    """Pass when the input contains only digits."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        if re.fullmatch(r'[\d]+', str(input)) is not None:
            return True
        return ['numeric_error', [input]]

    def json_schema(self):
        return {"type": "string", "pattern": r"^[\d]+$"}


class Accepted(Rule):
    """Pass for common affirmative values such as yes, on, or 1."""

    def __call__(self, input) -> any:
        if input is None:
            return True
        string_result = String()(input)
        if string_result is True:
            input = input.lower()
        acceptable = ['yes', 'on', '1', 1, True, 'true']
        if input in acceptable:
            return True
        return ['accepted_error', [input]]

    def json_schema(self):
        return {"enum": ['yes', 'on', '1', 1, True, 'true']}

class Email(Rule):
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

        is_string = String()(input)
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

    def json_schema(self):
        return {"format": "email"}

class In(Rule):
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

    def json_schema(self):
        return {"enum": list(self.vars)}

class NotIn(Rule):
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

    def json_schema(self):
        return {"not": {"enum": list(self.vars)}}

class Regex(Rule):
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

    def json_schema(self):
        return {"pattern": self.rule}

class Url(Rule):
    """Pass when the input is a valid URL."""

    _pattern = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"

    def __call__(self, input) -> any:
        if input is None:
            return True
        string_result = String()(input)
        if string_result is not True:
            return string_result
        if re.fullmatch(self._pattern, input) is not None:
            return True
        return ['url_error', [input]]

    def json_schema(self):
        return {"type": "string", "format": "uri"}


class Ip(Rule):
    """Pass when the input is a valid IPv4 address."""

    _pattern = r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"

    def __call__(self, input) -> any:
        if input is None:
            return True
        string_result = String()(input)
        if string_result is not True:
            return string_result
        ipv = re.match(self._pattern, input)
        if ipv is not None and all(0 <= int(number) <= 255 for number in ipv.groups()):
            return True
        return ['ip_error', [input]]

    def json_schema(self):
        return {"type": "string", "format": "ipv4"}

class Extension(Rule):
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

    def json_schema(self):
        suffixes = [re.escape(str(extension)) for extension in self.allowed]
        return {"pattern": rf"(?:{'|'.join(suffixes)})$"} if suffixes else {}

class Unique(Rule):
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

    def json_schema(self):
        return {}

class Exists(Rule):
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

    def json_schema(self):
        return {}

class ExistsCount(Rule):
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

    def json_schema(self):
        return {}

class FileSize(Rule):
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

    def json_schema(self):
        return {}


class Each(Rule):
    """Apply a set of rules to every item of a collection."""

    def __init__(self, *rules):
        """Set the rules applied to each item.

        Parameters
        ----------
        rules:
            Rules to run against every collection item.
        """
        normalized = []
        for rule in rules:
            if isinstance(rule, type) and issubclass(rule, Rule):
                rule = rule()
            if not isinstance(rule, Rule):
                raise TypeError("Validation rules must inherit Rule")
            normalized.append(rule)
        self.rules = tuple(normalized)

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

    def json_schema(self):
        fragments = []
        for rule in self.rules:
            exporter = getattr(rule, "json_schema", None)
            if callable(exporter):
                fragment = exporter()
                if fragment:
                    fragments.append(fragment)
        return {"items": {"allOf": fragments}} if fragments else {}

class MaxDepth(Rule):
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

    def json_schema(self):
        return {}

class Or(Rule):
    """Pass when at least one of the given rules passes."""

    def __init__(self, *rules):
        """Set the rules to try.

        Parameters
        ----------
        rules:
            Rules of which at least one must pass.
        """
        normalized = []
        for rule in rules:
            if isinstance(rule, type) and issubclass(rule, Rule):
                rule = rule()
            if not isinstance(rule, Rule):
                raise TypeError("Validation rules must inherit Rule")
            normalized.append(rule)
        self.rules = tuple(normalized)

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

    def json_schema(self):
        fragments = []
        for rule in self.rules:
            exporter = getattr(rule, "json_schema", None)
            if callable(exporter):
                fragment = exporter()
                if fragment:
                    fragments.append(fragment)
        return {"anyOf": fragments} if fragments else {}

class And(Rule):
    """Pass when all of the given rules pass."""

    def __init__(self, *rules):
        """Set the rules that must all pass.

        Parameters
        ----------
        rules:
            Rules of which every one must pass.
        """
        normalized = []
        for rule in rules:
            if isinstance(rule, type) and issubclass(rule, Rule):
                rule = rule()
            if not isinstance(rule, Rule):
                raise TypeError("Validation rules must inherit Rule")
            normalized.append(rule)
        self.rules = tuple(normalized)

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

    def json_schema(self):
        fragments = []
        for rule in self.rules:
            exporter = getattr(rule, "json_schema", None)
            if callable(exporter):
                fragment = exporter()
                if fragment:
                    fragments.append(fragment)
        return {"allOf": fragments} if fragments else {}
