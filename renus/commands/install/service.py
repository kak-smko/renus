import urllib.request
import urllib.error
import typing
from email.message import Message

class Response(typing.NamedTuple):
    content: bytes
    head: Message
    status_code: int
    @property
    def headers(self):
        res={}
        h=self.head.items()
        for item in h:
            res[item[0]]=item[1]
        return res


def request(
    url: str
) -> Response:
    method = 'GET'

    headers = {"Accept": "*"}

    httprequest = urllib.request.Request(
        url,  headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(httprequest) as httpresponse:
            response = Response(
                head=httpresponse.headers,
                status_code=httpresponse.status,
                content=httpresponse.read()
            )
    except urllib.error.HTTPError as e:
        response = Response(
            content=bytes(e.reason),
            head=e.headers,
            status_code=e.code
        )

    return response
