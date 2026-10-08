"""Repositórios em memória para os testes da API administrativa (F23 §6.1).

`FakeDb.transaction()` tira um snapshot do estado e o restaura se o bloco levantar,
o que permite testar o rollback sem banco.
"""

import copy
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import bcrypt

from repositories.access_token_repo import AccessToken
from repositories.user_repo import User
from security.token_auth import hash_token

ADMIN_PASSWORD = "Admin#123"


def bcrypt_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


class Store:
    def __init__(self) -> None:
        self.users: dict[UUID, dict] = {}
        self.profiles: dict[UUID, dict] = {}
        self.analyses: dict[UUID, dict] = {}
        self.user_profiles: set[tuple[UUID, UUID]] = set()
        self.profile_analyses: set[tuple[UUID, UUID]] = set()
        self.tokens: dict[UUID, dict] = {}
        self.history_user_ids: set[UUID] = set()
        self.data_sources: dict[UUID, dict] = {}  # F24
        self.steps: dict[UUID, dict] = {}  # F24: step_id -> linha
        self.history_analysis_ids: set[UUID] = set()  # F24
        self.clock = 0  # F24: relógio fake de updated_at

    def snapshot(self):
        return copy.deepcopy(self.__dict__)

    def restore(self, state) -> None:
        self.__dict__.update(state)

    def add_user(self, name="Maria", email="maria@empresa.com", password="Senh@123", is_admin=False,
                 is_blocked=False) -> UUID:
        user_id = uuid4()
        self.users[user_id] = dict(
            id=user_id, name=name, external_id=email, password_hash=bcrypt_hash(password),
            is_blocked=is_blocked, is_admin=is_admin, created_by=None,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        return user_id

    def add_profile(self, name="Comercial", is_active=True) -> UUID:
        pid = uuid4()
        self.profiles[pid] = dict(
            id=pid, name=name, description=None, is_active=is_active,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        return pid

    def add_analysis(self, name="Vendas", is_active=True) -> UUID:
        aid = uuid4()
        self.analyses[aid] = dict(
            id=aid, name=name, is_active=is_active, description=None, data_source_id=None,
            cache_frequency="daily", parameters={}, created_by=None,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        return aid

    def tick(self) -> datetime:
        self.clock += 1
        return datetime(2026, 6, 1) + timedelta(seconds=self.clock)

    def add_data_source(self, name="vendas_db", type_="postgresql", is_active=True, config=None) -> UUID:
        from security.crypto import encrypt_password

        did = uuid4()
        self.data_sources[did] = dict(
            id=did, name=name, type=type_, is_active=is_active, created_by=None,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
            connection_config=config or dict(
                host="h", port=5432, database="d", user="u", password=encrypt_password("segredo")
            ),
        )
        return did

    def add_full_analysis(self, name="vendas", ds_id=None, sql="SELECT 1 WHERE :a = 1",
                          step_params=("a",), parameters=None, with_step=True) -> UUID:
        aid = self.add_analysis(name)
        self.analyses[aid].update(
            data_source_id=ds_id,
            parameters=parameters if parameters is not None else {"a": {"type": "integer", "required": True}},
        )
        if with_step:
            sid = uuid4()
            self.steps[sid] = dict(id=sid, analysis_id=aid, step_order=1, step_type="query",
                                   definition={"sql": sql, "params": list(step_params)})
        return aid

    def add_token(self, user_id: UUID, raw: str, days: int = 1, revoked: bool = False) -> UUID:
        tid = uuid4()
        self.tokens[tid] = dict(
            id=tid, user_id=user_id, token_hash=hash_token(raw), label=None,
            expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            revoked_at=datetime.now(timezone.utc) if revoked else None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_used_at=None,
        )
        return tid


class FakeDb:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1
        state = self.store.snapshot()
        try:
            yield self
        except BaseException:
            self.store.restore(state)
            raise


def _contains(text: str | None, q: str | None) -> bool:
    return q is None or (text is not None and q.strip("%").replace("\\", "").lower() in text.lower())


class FakeUserRepo:
    def __init__(self, store: Store) -> None:
        self.s = store

    def _user(self, row) -> User:
        return User(row["id"], row["name"], row["external_id"], row["password_hash"],
                    row["is_blocked"], row["is_admin"])

    async def get_by_id(self, user_id, db=None):
        row = self.s.users.get(user_id)
        return self._user(row) if row else None

    async def get_by_external_id(self, external_id):
        row = next((r for r in self.s.users.values() if r["external_id"] == external_id), None)
        return self._user(row) if row else None

    async def list_page(self, q, is_blocked, profile_id, limit, offset):
        rows = [
            r for r in self.s.users.values()
            if (_contains(r["name"], q) or _contains(r["external_id"], q))
            and (is_blocked is None or r["is_blocked"] == is_blocked)
            and (profile_id is None or (r["id"], profile_id) in self.s.user_profiles)
        ]
        rows.sort(key=lambda r: (r["name"], str(r["id"])))
        return [self._public(r) for r in rows[offset:offset + limit]], len(rows)

    @staticmethod
    def _public(row):
        return {k: v for k, v in row.items() if k != "password_hash"}

    async def get_admin_row(self, user_id, db=None):
        row = self.s.users.get(user_id)
        return self._public(row) if row else None

    async def create(self, name, email, password_hash, is_admin, created_by, db=None):
        user_id = uuid4()
        self.s.users[user_id] = dict(
            id=user_id, name=name, external_id=email, password_hash=password_hash,
            is_blocked=False, is_admin=is_admin, created_by=created_by,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        return user_id

    async def update(self, user_id, fields, db=None):
        if user_id not in self.s.users:
            return False
        self.s.users[user_id].update(fields)
        return True

    async def delete(self, user_id, db=None):
        if self.s.users.pop(user_id, None) is None:
            return False
        self.s.user_profiles = {p for p in self.s.user_profiles if p[0] != user_id}
        self.s.tokens = {k: v for k, v in self.s.tokens.items() if v["user_id"] != user_id}
        return True

    async def has_history(self, user_id, db=None):
        return user_id in self.s.history_user_ids

    async def lock_active_admin_ids(self, db):
        return {r["id"] for r in self.s.users.values() if r["is_admin"] and not r["is_blocked"]}

    async def get_profiles(self, user_id, db=None):
        return [
            {k: self.s.profiles[pid][k] for k in ("id", "name", "is_active")}
            for uid, pid in sorted(self.s.user_profiles, key=lambda p: str(p[1])) if uid == user_id
        ]

    async def existing_profile_ids(self, profile_ids, db=None):
        return {i for i in profile_ids if i in self.s.profiles}

    async def replace_profiles(self, user_id, profile_ids, db):
        self.s.user_profiles = {p for p in self.s.user_profiles if p[0] != user_id}
        self.s.user_profiles |= {(user_id, pid) for pid in profile_ids}


class FakeTokenRepo:
    def __init__(self, store: Store) -> None:
        self.s = store

    async def get_by_hash(self, token_hash):
        row = next((t for t in self.s.tokens.values() if t["token_hash"] == token_hash), None)
        return AccessToken(row["id"], row["user_id"], row["token_hash"], row["label"],
                           row["expires_at"], row["revoked_at"]) if row else None

    async def touch_last_used(self, token_id):
        self.s.tokens[token_id]["last_used_at"] = datetime.now(timezone.utc)

    async def list_by_user(self, user_id):
        return [
            {k: t[k] for k in ("id", "label", "created_at", "expires_at", "revoked_at", "last_used_at")}
            for t in self.s.tokens.values() if t["user_id"] == user_id
        ]

    async def count_active(self, user_id):
        now = datetime.now(timezone.utc)
        return sum(1 for t in self.s.tokens.values()
                   if t["user_id"] == user_id and t["revoked_at"] is None and t["expires_at"] > now)

    async def revoke_for_user(self, token_id, user_id):
        token = self.s.tokens.get(token_id)
        if token is None or token["user_id"] != user_id:
            return False
        token["revoked_at"] = token["revoked_at"] or datetime.now(timezone.utc)
        return True

    async def revoke_all(self, user_id, db=None):
        n = 0
        for t in self.s.tokens.values():
            if t["user_id"] == user_id and t["revoked_at"] is None:
                t["revoked_at"] = datetime.now(timezone.utc)
                n += 1
        return n


class FakeProfileRepo:
    def __init__(self, store: Store) -> None:
        self.s = store

    def _summary(self, p):
        return {
            **p,
            "users_count": sum(1 for _, pid in self.s.user_profiles if pid == p["id"]),
            "analyses_count": sum(1 for pid, _ in self.s.profile_analyses if pid == p["id"]),
        }

    async def list_page(self, q, is_active, limit, offset):
        rows = [p for p in self.s.profiles.values()
                if _contains(p["name"], q) and (is_active is None or p["is_active"] == is_active)]
        rows.sort(key=lambda p: (p["name"], str(p["id"])))
        return [self._summary(p) for p in rows[offset:offset + limit]], len(rows)

    async def get_summary(self, profile_id, db=None):
        p = self.s.profiles.get(profile_id)
        return self._summary(p) if p else None

    async def create(self, name, description, is_active, db=None):
        if any(p["name"] == name for p in self.s.profiles.values()):
            import asyncpg

            raise asyncpg.UniqueViolationError("duplicate")
        pid = self.s.add_profile(name, is_active)
        self.s.profiles[pid]["description"] = description
        return pid

    async def update(self, profile_id, fields, db=None):
        if profile_id not in self.s.profiles:
            return False
        if "name" in fields and any(
            p["name"] == fields["name"] and p["id"] != profile_id for p in self.s.profiles.values()
        ):
            import asyncpg

            raise asyncpg.UniqueViolationError("duplicate")
        self.s.profiles[profile_id].update(fields)
        return True

    async def delete(self, profile_id, db=None):
        if self.s.profiles.pop(profile_id, None) is None:
            return False
        self.s.user_profiles = {p for p in self.s.user_profiles if p[1] != profile_id}
        self.s.profile_analyses = {p for p in self.s.profile_analyses if p[0] != profile_id}
        return True

    async def get_users(self, profile_id, db=None):
        return [
            dict(id=u["id"], name=u["name"], email=u["external_id"], is_blocked=u["is_blocked"])
            for (uid, pid) in self.s.user_profiles if pid == profile_id
            for u in [self.s.users[uid]]
        ]

    async def get_analyses(self, profile_id, db=None):
        return [self.s.analyses[aid] for (pid, aid) in self.s.profile_analyses if pid == profile_id]

    async def existing_ids(self, table, ids, db=None):
        source = {"users": self.s.users, "analyses": self.s.analyses, "profiles": self.s.profiles}[table]
        return {i for i in ids if i in source}

    async def replace_analyses(self, profile_id, analysis_ids, db):
        self.s.profile_analyses = {p for p in self.s.profile_analyses if p[0] != profile_id}
        self.s.profile_analyses |= {(profile_id, a) for a in analysis_ids}

    async def replace_users(self, profile_id, user_ids, db):
        self.s.user_profiles = {p for p in self.s.user_profiles if p[1] != profile_id}
        self.s.user_profiles |= {(u, profile_id) for u in user_ids}


# ---- F24 ----


class FakeDataSourceRepo:
    def __init__(self, store: Store) -> None:
        self.s = store

    def _count(self, did):
        return sum(1 for a in self.s.analyses.values() if a["data_source_id"] == did)

    def _summary(self, d):
        keys = ("id", "name", "type", "is_active", "created_by", "created_at", "updated_at")
        return {**{k: d[k] for k in keys}, "analyses_count": self._count(d["id"])}

    async def get_by_id(self, ds_id, db=None):
        from repositories.data_source_repo import DataSource

        d = self.s.data_sources.get(ds_id)
        return DataSource(d["id"], d["name"], d["type"], copy.deepcopy(d["connection_config"]),
                          d["is_active"]) if d else None

    async def list_page(self, q, type_, is_active, limit, offset):
        rows = [d for d in self.s.data_sources.values()
                if _contains(d["name"], q) and (type_ is None or d["type"] == type_)
                and (is_active is None or d["is_active"] == is_active)]
        rows.sort(key=lambda d: (d["name"], str(d["id"])))
        return [self._summary(d) for d in rows[offset:offset + limit]], len(rows)

    async def get_summary(self, ds_id, db=None):
        d = self.s.data_sources.get(ds_id)
        return self._summary(d) if d else None

    async def get_analyses(self, ds_id, db=None):
        return [{k: a[k] for k in ("id", "name", "is_active")}
                for a in self.s.analyses.values() if a["data_source_id"] == ds_id]

    async def create(self, name, type_, connection_config, is_active, created_by, db=None):
        if any(d["name"] == name for d in self.s.data_sources.values()):
            import asyncpg

            raise asyncpg.UniqueViolationError("duplicate")
        did = self.s.add_data_source(name, type_, is_active, copy.deepcopy(connection_config))
        self.s.data_sources[did]["created_by"] = created_by
        return did

    async def update(self, ds_id, fields, db=None):
        if ds_id not in self.s.data_sources:
            return False
        if "name" in fields and any(
            d["name"] == fields["name"] and d["id"] != ds_id for d in self.s.data_sources.values()
        ):
            import asyncpg

            raise asyncpg.UniqueViolationError("duplicate")
        self.s.data_sources[ds_id].update(copy.deepcopy(fields))
        self.s.data_sources[ds_id]["updated_at"] = self.s.tick()
        return True

    async def delete(self, ds_id, db=None):
        return self.s.data_sources.pop(ds_id, None) is not None

    async def touch_analyses(self, ds_id, db=None):
        for a in self.s.analyses.values():
            if a["data_source_id"] == ds_id:
                a["updated_at"] = self.s.tick()


class FakeAnalysisRepo:
    def __init__(self, store: Store) -> None:
        self.s = store

    def _summary(self, a):
        ds = self.s.data_sources.get(a["data_source_id"])
        keys = ("id", "name", "description", "data_source_id", "cache_frequency", "is_active",
                "created_by", "created_at", "updated_at")
        return {**{k: a[k] for k in keys}, "data_source_name": ds["name"] if ds else None,
                "profiles_count": sum(1 for _, aid in self.s.profile_analyses if aid == a["id"])}

    async def admin_list(self, q, data_source_id, is_active, limit, offset):
        rows = [a for a in self.s.analyses.values()
                if (_contains(a["name"], q) or _contains(a["description"], q))
                and (data_source_id is None or a["data_source_id"] == data_source_id)
                and (is_active is None or a["is_active"] == is_active)]
        rows.sort(key=lambda a: (a["name"], str(a["id"])))
        return [self._summary(a) for a in rows[offset:offset + limit]], len(rows)

    async def get_admin_row(self, analysis_id, db=None):
        a = self.s.analyses.get(analysis_id)
        return {**self._summary(a), "parameters": copy.deepcopy(a["parameters"])} if a else None

    async def get_steps(self, analysis_id, db=None):
        from repositories.analysis_repo import AnalysisStep

        return [AnalysisStep(s["id"], s["analysis_id"], s["step_order"], s["step_type"],
                             copy.deepcopy(s["definition"]))
                for s in sorted(self.s.steps.values(), key=lambda s: s["step_order"])
                if s["analysis_id"] == analysis_id]

    async def get_profiles(self, analysis_id, db=None):
        return [{k: self.s.profiles[pid][k] for k in ("id", "name", "is_active")}
                for pid, aid in self.s.profile_analyses if aid == analysis_id]

    async def create(self, fields, db=None):
        if any(a["name"] == fields["name"] for a in self.s.analyses.values()):
            import asyncpg

            raise asyncpg.UniqueViolationError("duplicate")
        aid = self.s.add_analysis(fields["name"], fields["is_active"])
        self.s.analyses[aid].update(copy.deepcopy(fields))
        self.s.analyses[aid]["updated_at"] = self.s.tick()
        return aid

    async def create_step(self, analysis_id, definition, db=None):
        sid = uuid4()
        self.s.steps[sid] = dict(id=sid, analysis_id=analysis_id, step_order=1, step_type="query",
                                 definition=copy.deepcopy(definition))
        return sid

    async def update_step(self, step_id, definition, db=None):
        self.s.steps[step_id]["definition"] = copy.deepcopy(definition)

    async def update(self, analysis_id, fields, db=None):
        a = self.s.analyses.get(analysis_id)
        if a is None:
            return False
        if "name" in fields and any(
            x["name"] == fields["name"] and x["id"] != analysis_id for x in self.s.analyses.values()
        ):
            import asyncpg

            raise asyncpg.UniqueViolationError("duplicate")
        a.update(copy.deepcopy(fields))
        a["updated_at"] = self.s.tick()
        return True

    async def touch(self, analysis_id, db=None):
        a = self.s.analyses.get(analysis_id)
        if a is None:
            return None
        a["updated_at"] = self.s.tick()
        return a["updated_at"]

    async def has_history(self, analysis_id, db=None):
        return analysis_id in self.s.history_analysis_ids

    async def delete(self, analysis_id, db=None):
        if self.s.analyses.pop(analysis_id, None) is None:
            return False
        self.s.steps = {k: v for k, v in self.s.steps.items() if v["analysis_id"] != analysis_id}
        self.s.profile_analyses = {p for p in self.s.profile_analyses if p[1] != analysis_id}
        return True

    async def replace_profiles(self, analysis_id, profile_ids, db):
        self.s.profile_analyses = {p for p in self.s.profile_analyses if p[1] != analysis_id}
        self.s.profile_analyses |= {(pid, analysis_id) for pid in profile_ids}
