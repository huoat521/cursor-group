from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.core.expection import ValidateError
from app.core.log import logger


@dataclass
class LdapIdentity:
    username: str
    email: str | None = None
    full_name: str | None = None
    external_id: str | None = None


def authenticate_ldap(username: str, password: str) -> LdapIdentity:
    if not settings.AUTH_LDAP_ENABLED:
        raise ValidateError(error_info="LDAP 未启用")
    if not settings.LDAP_SERVER_URI or not settings.LDAP_USER_SEARCH_BASE:
        raise ValidateError(error_info="LDAP 配置不完整")
    try:
        from ldap3 import ALL, Connection, Server, Tls
        from ldap3.core.exceptions import LDAPException
    except ImportError as exc:
        raise ValidateError(error_info="未安装 ldap3 依赖") from exc

    try:
        server = Server(
            settings.LDAP_SERVER_URI,
            use_ssl=settings.LDAP_USE_SSL,
            get_info=ALL,
        )
        # optional service bind for search
        if settings.LDAP_BIND_DN:
            conn = Connection(
                server,
                user=settings.LDAP_BIND_DN,
                password=settings.LDAP_BIND_PASSWORD,
                auto_bind=True,
            )
        else:
            conn = Connection(server, auto_bind=True)

        user_filter = settings.LDAP_USER_FILTER.format(username=username)
        conn.search(
            settings.LDAP_USER_SEARCH_BASE,
            user_filter,
            attributes=[
                settings.LDAP_ATTR_USERNAME,
                settings.LDAP_ATTR_EMAIL,
                settings.LDAP_ATTR_DISPLAY_NAME,
            ],
        )
        if not conn.entries:
            raise ValidateError(error_info="LDAP 用户不存在")
        entry = conn.entries[0]
        user_dn = entry.entry_dn
        conn.unbind()

        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        attrs = entry.entry_attributes_as_dict

        def _first(key: str) -> str | None:
            vals = attrs.get(key) or []
            return str(vals[0]) if vals else None

        identity = LdapIdentity(
            username=_first(settings.LDAP_ATTR_USERNAME) or username,
            email=_first(settings.LDAP_ATTR_EMAIL),
            full_name=_first(settings.LDAP_ATTR_DISPLAY_NAME),
            external_id=user_dn,
        )
        user_conn.unbind()
        return identity
    except ValidateError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("LDAP auth failed: %s", exc)
        raise ValidateError(error_info="LDAP 认证失败") from exc
