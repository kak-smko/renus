import os
import re


class Default:
    def __init__(self, data):
        self.d = data

    def __call__(self, input):
        if input is None:
            return self.d
        return True


class Convert:
    def __init__(self, func=None, inputs: list = None):
        self.func = func
        self.inputs = inputs

    def __call__(self, input):
        if self.inputs is not None:
            for i in self.inputs:
                if i[0] == input:
                    return i[1]
            return input
        return self.func(input)


def Required(input) -> any:
    if input is not None:
        return True
    return 'required_error'


def String(input) -> any:
    if input is None:
        return True
    t = type(input)
    if t is str:
        return True
    return ['type_error', ['string', str(t)]]


def Bool(input) -> any:
    if input is None:
        return True
    t = type(input)
    if t is bool:
        return True
    return ['type_error', ['bool', str(t)]]


def List(input) -> any:
    if input is None:
        return True
    t = type(input)
    if t is list:
        return True
    return ['type_error', ['list', str(t)]]


def Dict(input) -> any:
    if input is None:
        return True
    t = type(input)
    if t is dict:
        return True
    return ['type_error', ['dict', str(t)]]


def Int(input) -> any:
    if input is None:
        return True
    t = type(input)
    if t is int:
        return True
    return ['type_error', ['int', str(t)]]


def Float(input) -> any:
    if input is None:
        return True
    t = type(input)
    if t is float or t is int:
        return True

    return ['type_error', ['float', str(t)]]


class Len:
    def __init__(self, length: int):
        self.l = length

    def __call__(self, input):
        if input is None:
            return True
        length = len(input)
        if length == self.l:
            return True
        return ['len_error', [self.l, length]]


class MinLen:
    def __init__(self, length: int):
        self.l = length

    def __call__(self, input):
        if input is None:
            return True
        length = len(input)
        if length >= self.l:
            return True
        return ['min_len_error', [self.l, length]]


class MaxLen:
    def __init__(self, length: int):
        self.l = length

    def __call__(self, input):
        if input is None:
            return True
        length = len(input)
        if length <= self.l:
            return True
        return ['max_len_error', [self.l, length]]


class Eq:
    def __init__(self, length: float):
        self.l = length

    def __call__(self, input):
        if input is None:
            return True

        if input == self.l:
            return True
        return ['eq_error', [self.l, input]]


class Min:
    def __init__(self, length: float):
        self.l = length

    def __call__(self, input):
        if input is None:
            return True

        if input >= self.l:
            return True
        return ['min_error', [self.l, input]]


class Max:
    def __init__(self, length: float):
        self.l = length

    def __call__(self, input):
        if input is None:
            return True

        if input <= self.l:
            return True
        return ['max_error', [self.l, input]]


def Numeric(input) -> any:
    if input is None:
        return True
    if re.compile('[\d]+').fullmatch(str(input)) != None:
        return True
    return ['numeric_error', [input]]


def Accepted(input) -> any:
    if input is None:
        return True
    if String(input) == True:
        input = input.lower()
    acceptable = ['yes', 'on', '1', 1, True, 'true']
    if input in acceptable:
        return True
    return ['accepted_error', [input]]


class Email:
    def __init__(self, allow_domain: list = None):
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
        if len(self.allow_domain) > 0:
            if domain not in self.allow_domain:
                return ['email_domain_allow_error', [domain, str(self.allow_domain)]]
        if len(name) < 3:
            return ['email_name_error', [3, input]]

        return True


class In:
    def __init__(self, *vars):
        self.vars = list(vars)

    def __call__(self, input):
        if input is None:
            return True
        if input in self.vars:
            return True
        return ['in_error', [input, str(self.vars)]]


class NotIn:
    def __init__(self, *vars):
        self.vars = list(vars)

    def __call__(self, input):
        if input is None:
            return True

        if input not in self.vars:
            return True
        return ['not_in_error', [input, str(self.vars)]]


class Regex:
    def __init__(self, rule: str, msg: str = None):
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
    def __init__(self, extensions: list = None):
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
            return ['image_error', [string]]
        return True


class Unique:
    def __init__(self, model, field, current_id=None):
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
    def __init__(self, model, field):
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
    def __init__(self, model, field, count: int = None, minCount: int = None, maxCount: int = None):
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
    def __init__(self, max_byte: int = 0, min_byte: int = 0, delete=True, replace: list = None, item_dict: str = None):
        """
        @param max_byte: maximum allowed Bytes
        @param min_byte:minimum allowed Bytes
        @param delete: delete file if not passed
        @param replace: replace file path. default is [('storage/img/','storage/'),('storage/','storage/public/')]
        @param item_dict: if file path in a dict. ex {url:'',meta:''} => item_dict='url'
        """
        if replace is None:
            replace = [('storage/img/', 'storage/'), ('storage/', 'storage/public/')]
        self.delete = delete
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
        if passed is not True and self.delete:
            for item in input:
                tt = type(item)
                if tt is dict:
                    link = item[self.item_dict]
                else:
                    link = item
                for rep in self.replace:
                    link = link.replace(rep[0], rep[1])

                os.remove(link)

        return passed
