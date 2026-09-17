"""Local, file-backed drop-in replacement for the Firestore client.

Implements the small subset of the google-cloud-firestore API that
app.py relies on (collection/document/get/set/update/delete/where/
limit/stream/add), backed by a single JSON file on disk instead of a
remote Firestore database. This keeps app.py, models.py, etc. free of
any Firestore-specific code changes.
"""
import copy
import json
import os
import threading
import uuid

_DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'local_db.json')


class _Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self._data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, 'r') as f:
                self._data = json.load(f)
        else:
            self._data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f'{self.path}.tmp'
        with open(tmp, 'w') as f:
            json.dump(self._data, f, indent=2, default=str)
        os.replace(tmp, self.path)

    def resolve_collection(self, parts, create=False):
        """Walk alternating collection/document path segments and
        return the dict mapping doc_id -> doc for the final collection."""
        node = self._data
        i = 0
        while i < len(parts):
            coll_name = parts[i]
            if coll_name not in node:
                if not create:
                    return None
                node[coll_name] = {}
            node = node[coll_name]
            i += 1
            if i < len(parts):
                doc_id = parts[i]
                if doc_id not in node:
                    if not create:
                        return None
                    node[doc_id] = {'__fields__': {}, '__subs__': {}}
                node = node[doc_id].setdefault('__subs__', {})
                i += 1
        return node


_store = _Store(_DB_PATH)


def _jsonify(data):
    return json.loads(json.dumps(data, default=str))


def _matches(fields, filters):
    for field, op, value in filters:
        actual = fields.get(field)
        if op == '==':
            if actual != value:
                return False
        else:
            raise NotImplementedError(f'Unsupported where() operator: {op}')
    return True


class DocumentSnapshot:
    def __init__(self, doc_id, fields, exists):
        self.id = doc_id
        self._fields = fields
        self.exists = exists

    def to_dict(self):
        return copy.deepcopy(self._fields) if self._fields is not None else None


class DocumentReference:
    def __init__(self, parts):
        self._parts = parts
        self.id = parts[-1]

    def collection(self, name):
        return CollectionReference(self._parts + [name])

    def get(self):
        with _store.lock:
            coll = _store.resolve_collection(self._parts[:-1])
            doc_id = self._parts[-1]
            if coll is None or doc_id not in coll:
                return DocumentSnapshot(doc_id, None, False)
            return DocumentSnapshot(doc_id, coll[doc_id].get('__fields__', {}), True)

    def set(self, data, merge=False):
        with _store.lock:
            coll = _store.resolve_collection(self._parts[:-1], create=True)
            doc_id = self._parts[-1]
            doc = coll.setdefault(doc_id, {'__fields__': {}, '__subs__': {}})
            if merge:
                doc['__fields__'].update(_jsonify(data))
            else:
                doc['__fields__'] = _jsonify(data)
            _store.save()

    def update(self, data):
        with _store.lock:
            coll = _store.resolve_collection(self._parts[:-1], create=True)
            doc_id = self._parts[-1]
            doc = coll.setdefault(doc_id, {'__fields__': {}, '__subs__': {}})
            doc['__fields__'].update(_jsonify(data))
            _store.save()

    def delete(self):
        with _store.lock:
            coll = _store.resolve_collection(self._parts[:-1])
            doc_id = self._parts[-1]
            if coll and doc_id in coll:
                del coll[doc_id]
                _store.save()


class Query:
    def __init__(self, parts, filters=None, limit_n=None):
        self._parts = parts
        self._filters = filters or []
        self._limit = limit_n

    def where(self, field, op, value):
        return Query(self._parts, self._filters + [(field, op, value)], self._limit)

    def limit(self, n):
        return Query(self._parts, self._filters, n)

    def stream(self):
        with _store.lock:
            coll = _store.resolve_collection(self._parts) or {}
            results = []
            for doc_id, doc in coll.items():
                fields = doc.get('__fields__', {})
                if _matches(fields, self._filters):
                    results.append(DocumentSnapshot(doc_id, fields, True))
        if self._limit is not None:
            results = results[:self._limit]
        return results


class CollectionReference:
    def __init__(self, parts):
        self._parts = parts

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = uuid.uuid4().hex
        return DocumentReference(self._parts + [doc_id])

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return (None, ref)

    def where(self, field, op, value):
        return Query(self._parts).where(field, op, value)

    def limit(self, n):
        return Query(self._parts).limit(n)

    def stream(self):
        return Query(self._parts).stream()


class LocalFirestoreClient:
    def collection(self, name):
        return CollectionReference([name])


fs = LocalFirestoreClient()
