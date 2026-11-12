"""Just enough of `fastapi` to import the route modules and call their handlers directly, used ONLY when the real package
is not installed (the sandbox this was written in had no package registry). With real FastAPI installed this does nothing and
the same tests run against the real library's decorators."""
from __future__ import annotations

import sys
import types


def install() -> bool:
    """Returns True when a stand-in was installed."""
    try:
        import fastapi  # noqa: F401

        return False
    except ModuleNotFoundError:
        pass
    # the very class FastAPI re-exports, so the stand-in behaves exactly like the real one: .tasks, add_task, `await bt()`
    from starlette.background import BackgroundTasks
    from starlette.responses import JSONResponse, Response

    class Depends:
        def __init__(self, dependency=None):
            self.dependency = dependency

    class Request:  # only used as a type annotation by the dependencies
        pass

    def File(*args, **kwargs):  # noqa: N802 - mirrors fastapi's names; only used as parameter defaults, never called by the tests
        return None

    Form = File  # noqa: N816

    class UploadFile:  # annotation only
        pass

    class APIRouter:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def _route(self, method):
            def decorator(path, **kw):
                def wrap(fn):
                    self.routes.append((method, path, fn, kw))
                    return fn

                return wrap

            return decorator

        def __getattr__(self, name):
            if name in {"get", "post", "put", "patch", "delete"}:
                return self._route(name.upper())
            raise AttributeError(name)

    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter, fastapi.Depends, fastapi.Request = APIRouter, Depends, Request
    fastapi.File, fastapi.Form, fastapi.UploadFile = File, Form, UploadFile
    fastapi.__getattr__ = lambda name: (lambda *a, **k: None)   # any other name (Query, Header, ...) is a harmless placeholder
    fastapi.BackgroundTasks, fastapi.Response = BackgroundTasks, Response
    responses = types.ModuleType("fastapi.responses")
    responses.JSONResponse, responses.Response = JSONResponse, Response
    fastapi.responses = responses
    sys.modules["fastapi"], sys.modules["fastapi.responses"] = fastapi, responses
    return True
