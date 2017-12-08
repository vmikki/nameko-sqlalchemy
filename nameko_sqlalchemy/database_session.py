import operator
from weakref import WeakKeyDictionary

import wrapt
from nameko.extensions import DependencyProvider
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import sessionmaker

DB_URIS_KEY = 'DB_URIS'


class DatabaseSession(DependencyProvider):
    def __init__(self, declarative_base):
        self.declarative_base = declarative_base
        self.sessions = WeakKeyDictionary()

    def setup(self):
        service_name = self.container.service_name
        decl_base_name = self.declarative_base.__name__
        uri_key = '{}:{}'.format(service_name, decl_base_name)

        db_uris = self.container.config[DB_URIS_KEY]
        self.db_uri = db_uris[uri_key].format({
            'service_name': service_name,
            'declarative_base_name': decl_base_name,
        })
        self.engine = create_engine(self.db_uri)

    def stop(self):
        self.engine.dispose()
        del self.engine

    def get_dependency(self, worker_ctx):

        session_cls = sessionmaker(bind=self.engine)
        session = session_cls()

        self.sessions[worker_ctx] = session
        return session

    def worker_teardown(self, worker_ctx):
        session = self.sessions.pop(worker_ctx)
        session.close()

# backwards compat
Session = DatabaseSession


def run_query(session, query, attempts=3):
    while attempts > 0:
        attempts -= 1
        try:
            return query()
        except exc.DBAPIError as exception:
            if attempts > 0 and exception.connection_invalidated:
                session.rollback()
            else:
                raise
    else:  # pragma: no cover
        pass


def transaction_retry(session, attempts=3):
    @wrapt.decorator
    def wrapper(wrapped, instance, args, kwargs):
        if isinstance(session, operator.attrgetter):
            return run_query(session(instance), wrapped, attempts)

        return run_query(session, wrapped, attempts)

    return wrapper
