"""Expose the same HTTP handlers through Gunicorn's bounded production workers."""
import io
from types import SimpleNamespace
from server import Handler

STATE = SimpleNamespace(attempts=[])


class WSGIHandler(Handler):
    def __init__(self, environ):
        self.path = environ.get('PATH_INFO', '/')
        self.headers = {key[5:].replace('_', '-').title(): value
                        for key, value in environ.items() if key.startswith('HTTP_')}
        self.headers['Content-Type'] = environ.get('CONTENT_TYPE', '')
        self.headers['Content-Length'] = environ.get('CONTENT_LENGTH', '0') or '0'
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.server = STATE
        self.response_headers = []

    def send_response(self, status):
        from http import HTTPStatus
        self.status = f'{status} {HTTPStatus(status).phrase}'

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass


def application(environ, start_response):
    handler = WSGIHandler(environ)
    method = environ.get('REQUEST_METHOD')
    if method == 'GET':
        handler.do_GET()
    elif method == 'POST':
        handler.do_POST()
    else:
        handler.send(405, {'error': '不支援此操作'}, headers={'Allow': 'GET, POST'})
    start_response(handler.status, handler.response_headers)
    return [handler.wfile.getvalue()]
