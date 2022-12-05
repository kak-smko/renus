from html.parser import HTMLParser
from html import unescape

class Injection:
    def escape(self, value:str):
        parser = Xss()
        parser.feed(unescape(value))
        parser.close()
        return parser.getEscaped().strip()

    def protect(self, data):
        return self.__value_handle(data)

    def __list_handle(self, data):
        res = []
        for item in data:
            res.append(self.__value_handle(item))
        return res

    def __value_handle(self, value):
        typ = type(value)
        if value is None or typ in [bool, int, float]:
            v = value
        elif typ is dict:
            v = self.__dict_handle(value)
        elif typ is list:
            v = self.__list_handle(value)
        else:
            v = self.escape(str(value))
        return v

    def __dict_handle(self, obj: dict):
        res = {}
        for key, value in obj.items():
            res[self.escape(str(key))] = self.__value_handle(value)
        return res


class Xss(HTMLParser):
    block_tags = {
        'script': 'scrlpt',
    }
    allow_protocol=['http','https']
    allow_attr = {'class':1,
                  'id':1,
                  'href':['a'],
                  'target':['a'],
                  'alt':['img'],
                  'width':['img','video'],
                  'height':['img','video'],
                  'controls':['video'],
                  'src':['img','video']
                  }
    no_end_tags = ["img", "hr", "br", "embed"]

    def __init__(self):
        HTMLParser.__init__(self)
        self.result = []
        self.start_list = []

    def getEscaped(self):
        return self._htmlspecialchars(''.join(self.result))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag, attrs):
        if tag in self.block_tags:
            tag = self.block_tags[tag]
        end_diagonal = ' /' if tag in self.no_end_tags else ''
        if not end_diagonal:
            self.start_list.append(tag)
        attdict = {}
        for attr in attrs:
            if attr[0] in self.allow_attr:
                if self.allow_attr[attr[0]]==1 or tag in self.allow_attr[attr[0]]:
                    attdict[attr[0]] =self._is_valid(attr)

        attrs = []
        for (key, value) in attdict.items():
            attrs.append('%s="%s"' % (key, self._htmlspecialchars(value)))
        attrs = (' ' + ' '.join(attrs)) if attrs else ''
        self.result.append('&lt;' + tag + attrs + end_diagonal + '&gt;')

    def handle_endtag(self, tag):
        if tag in self.block_tags:
            tag = self.block_tags[tag]
        if self.start_list and tag == self.start_list[len(self.start_list) - 1]:
            self.result.append('&lt;/' + tag + '&gt;')
            self.start_list.pop()

    def handle_data(self, data):
        self.result.append(self._htmlspecialchars(data))

    def handle_entityref(self, name):
        if name.isalpha():
            self.result.append("&%s;" % name)

    def handle_charref(self, name):
        if name.isdigit():
            self.result.append("&#%s;" % name)

    def _is_valid(self,attr):
        if attr[0] in ['href','src']:
            if str(attr[1]).find(':') !=-1:
                has =False
                for item in self.allow_protocol:
                    if str(attr[1]).startswith(item):
                        has=True
                if has is False:
                    return 'http://%s' % str(attr[1])
            elif str(attr[1]).startswith('//'):
                return 'http:%s' % str(attr[1])
        return attr[1]
    def _htmlspecialchars(self, html):
        return html.replace("<", "&lt;") \
            .replace(">", "&gt;") \
            .replace('"', "&quot;") \
            .replace("'", "&#039;")
