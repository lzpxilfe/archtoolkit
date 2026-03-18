# -*- coding: utf-8 -*-
"""
Gemini API helpers for ArchToolkit.

Goals
- No external Python dependencies (use Qt/QGIS network + stdlib only).
- Store API key in QGIS AuthManager (preferred) and keep only authcfg id in settings.
- Best-effort: never crash the plugin if AuthManager is unavailable/misconfigured.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Optional, Tuple

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QEventLoop, QSettings, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from .config import get_plugin_config_value
from .utils import push_message


_SETTINGS_PREFIX = "ArchToolkit/ai/gemini"
_DEPRECATED_MODEL_ALIASES = {
    "gemini-3-pro-preview": "gemini-3.1-pro-preview",
}
_DEPRECATED_MODEL_NOTES = {
    "gemini-3-pro-preview": "Google changelog 기준 2026-03-09에 종료되고 `gemini-3.1-pro-preview`로 대체되었습니다.",
}


def get_default_model_name() -> str:
    model = get_plugin_config_value("ai", "gemini", "default_model", default="gemini-3.1-pro-preview")
    out = str(model or "").strip()
    return out or "gemini-3.1-pro-preview"


def get_known_models() -> list[str]:
    values = get_plugin_config_value("ai", "gemini", "known_models", default=[])
    raw_models = values if isinstance(values, list) else []
    ordered = [get_default_model_name()] + [str(value or "").strip() for value in raw_models]
    out: list[str] = []
    for value in ordered:
        model = normalize_model_name(value)
        if model and model not in out:
            out.append(model)
    return out


def get_known_models_verified_at() -> str:
    value = get_plugin_config_value("ai", "gemini", "known_models_verified_at", default="")
    return str(value or "").strip()


def get_known_models_stale_after_days() -> int:
    value = get_plugin_config_value("ai", "gemini", "known_models_stale_after_days", default=14)
    try:
        days = int(value)
    except Exception:
        days = 14
    return max(1, days)


def _parse_verified_at(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def is_known_models_catalog_stale(verified_at: str = "") -> bool:
    parsed = _parse_verified_at(verified_at or get_known_models_verified_at())
    if parsed is None:
        return True
    try:
        age_days = (datetime.now() - parsed).days
    except Exception:
        return True
    return age_days >= get_known_models_stale_after_days()


def get_model_replacement(model: str) -> Optional[str]:
    name = str(model or "").strip()
    if not name:
        return None
    replacement = str(_DEPRECATED_MODEL_ALIASES.get(name) or "").strip()
    return replacement or None


def normalize_model_name(model: str) -> str:
    name = str(model or "").strip()
    if not name:
        return ""
    replacement = get_model_replacement(name)
    return replacement or name


def describe_model_status(
    model: str,
    *,
    verified_models: Optional[list[str]] = None,
    verified_at: str = "",
) -> Tuple[str, str]:
    raw_model = str(model or "").strip()
    if not raw_model:
        default_model = get_default_model_name()
        return "info", f"비워두면 기본 모델 `{default_model}`을 사용합니다."

    normalized = normalize_model_name(raw_model)
    replacement = get_model_replacement(raw_model)
    if replacement:
        note = _DEPRECATED_MODEL_NOTES.get(raw_model) or f"`{replacement}` 사용을 권장합니다."
        return "warning", f"현재 입력값 `{raw_model}`은 구형 ID입니다. {note}"

    known = list(verified_models or get_known_models())
    is_stale = is_known_models_catalog_stale(verified_at)
    if normalized in known:
        if is_stale:
            suffix = f" (마지막 확인일: {verified_at})" if str(verified_at or "").strip() else ""
            stale_days = get_known_models_stale_after_days()
            return "warning", (
                f"현재 모델 `{normalized}`은 저장된 목록에는 있지만, "
                f"확인일이 {stale_days}일 이상 지난 상태입니다{suffix}. '모델 확인'으로 갱신해보세요."
            )
        suffix = f" (공식 확인일: {verified_at})" if str(verified_at or "").strip() else ""
        return "ok", f"현재 모델 `{normalized}`은 최근 확인 목록에 있습니다{suffix}."

    if normalized == get_default_model_name():
        if is_stale:
            return "warning", (
                f"현재 모델 `{normalized}`은 플러그인 기본 모델이지만, "
                "내장 목록 확인일이 오래되어 최신 여부를 다시 확인하는 편이 안전합니다."
            )
        return "ok", f"현재 모델 `{normalized}`은 플러그인 기본 Gemini 모델입니다."

    return "warning", f"현재 모델 `{normalized}`은 최근 확인 목록에서 찾지 못했습니다. '모델 확인'으로 다시 검증해보세요."


def list_available_models(
    *,
    api_key: str,
    timeout_ms: int = 20000,
) -> Tuple[Optional[list[str]], Optional[str]]:
    """List current Gemini models that support generateContent."""
    api_key = str(api_key or "").strip()
    if not api_key:
        return None, "API key is missing"

    url = QUrl(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")

    try:
        from qgis.core import QgsNetworkAccessManager

        nam = QgsNetworkAccessManager.instance()
    except Exception:
        try:
            from qgis.PyQt.QtNetwork import QNetworkAccessManager

            nam = QNetworkAccessManager()
        except Exception:
            nam = None

    if nam is None:
        return None, "Network manager is unavailable"

    req = QNetworkRequest(url)
    try:
        reply = nam.get(req)
    except Exception as e:
        return None, f"Request failed: {e}"

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)

    def _on_timeout():
        try:
            reply.abort()
        except Exception:
            pass
        try:
            loop.quit()
        except Exception:
            pass

    def _on_finished():
        try:
            loop.quit()
        except Exception:
            pass

    try:
        timer.timeout.connect(_on_timeout)
        reply.finished.connect(_on_finished)
        timer.start(int(timeout_ms))
        loop.exec_()
    except Exception:
        pass

    try:
        if timer.isActive():
            timer.stop()
    except Exception:
        pass

    try:
        if reply.error():
            err = reply.errorString()
            try:
                body = bytes(reply.readAll()).decode("utf-8", "ignore")
            except Exception:
                body = ""
            return None, f"{err}\n{body}".strip()
    except Exception:
        pass

    try:
        raw = bytes(reply.readAll()).decode("utf-8", "ignore")
        obj = json.loads(raw) if raw else {}
    except Exception as e:
        return None, f"Invalid JSON response: {e}"

    try:
        models = obj.get("models") or []
        out: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            methods = [str(x or "").strip() for x in (item.get("supportedGenerationMethods") or [])]
            if methods and "generateContent" not in methods:
                continue
            name = str(item.get("name") or "").strip()
            if name.startswith("models/"):
                name = name[len("models/") :]
            if not name.startswith("gemini"):
                continue
            if name not in out:
                out.append(name)
        if out:
            return out, None
        return None, f"No Gemini models in response: {raw[:500]}"
    except Exception as e:
        return None, f"Failed to parse models response: {e}"


def _settings_get(key: str, default=None):
    try:
        return QSettings().value(f"{_SETTINGS_PREFIX}/{key}", default)
    except Exception:
        return default


def _settings_set(key: str, value) -> None:
    try:
        QSettings().setValue(f"{_SETTINGS_PREFIX}/{key}", value)
    except Exception:
        pass


def get_configured_model(default: str = "") -> str:
    fallback = str(default or "").strip() or get_default_model_name()
    raw = str(_settings_get("model", fallback) or "").strip()
    model = normalize_model_name(raw or fallback)
    if model and model != raw:
        _settings_set("model", model)
    return model or fallback


def set_configured_model(model: str) -> None:
    _settings_set("model", normalize_model_name(model))


def _auth_manager():
    try:
        from qgis.core import QgsApplication

        return QgsApplication.authManager()
    except Exception:
        return None


def _new_auth_config():
    try:
        from qgis.core import QgsAuthMethodConfig

        return QgsAuthMethodConfig()
    except Exception:
        return None


def _store_auth_config(auth_cfg) -> bool:
    authm = _auth_manager()
    if authm is None or auth_cfg is None:
        return False

    for name in ("storeAuthenticationConfig", "storeAuthMethodConfig"):
        fn = getattr(authm, name, None)
        if fn is None:
            continue
        try:
            return bool(fn(auth_cfg))
        except Exception:
            continue
    return False


def _update_auth_config(auth_cfg) -> bool:
    authm = _auth_manager()
    if authm is None or auth_cfg is None:
        return False

    for name in ("updateAuthenticationConfig", "updateAuthMethodConfig"):
        fn = getattr(authm, name, None)
        if fn is None:
            continue
        try:
            return bool(fn(auth_cfg))
        except Exception:
            continue
    return False


def _load_auth_config(authcfg_id: str):
    authm = _auth_manager()
    auth_cfg = _new_auth_config()
    if authm is None or auth_cfg is None:
        return None

    if not authcfg_id:
        return None

    for name in ("loadAuthenticationConfig", "loadAuthMethodConfig"):
        fn = getattr(authm, name, None)
        if fn is None:
            continue
        try:
            # Signature is typically (authcfg, config, full=True)
            ok = fn(str(authcfg_id), auth_cfg, True)
            if ok:
                return auth_cfg
        except TypeError:
            try:
                ok = fn(str(authcfg_id), auth_cfg)
                if ok:
                    return auth_cfg
            except Exception:
                continue
        except Exception:
            continue

    return None


def get_api_key() -> Optional[str]:
    """Return Gemini API key stored in QGIS AuthManager, if configured."""
    authcfg_id = str(_settings_get("authcfg", "") or "").strip()
    if not authcfg_id:
        return None

    auth_cfg = _load_auth_config(authcfg_id)
    if auth_cfg is None:
        return None

    try:
        # "Basic" method: password field holds the secret.
        key = str(auth_cfg.config("password") or "").strip()
        return key or None
    except Exception:
        return None


def configure_api_key(parent: QtWidgets.QWidget, *, iface=None) -> Optional[str]:
    """Prompt user for an API key and store it in AuthManager (best-effort).

    Returns the configured key (in-memory) on success, else None.
    """
    try:
        key, ok = QtWidgets.QInputDialog.getText(
            parent,
            "Gemini API Key",
            "Gemini API 키를 입력하세요 (QGIS 인증 저장소에 저장됩니다):",
            QtWidgets.QLineEdit.Password,
        )
    except Exception:
        return None

    if not ok:
        return None

    api_key = str(key or "").strip()
    if not api_key:
        return None

    authm = _auth_manager()
    auth_cfg = _new_auth_config()
    if authm is None or auth_cfg is None:
        if iface is not None:
            push_message(iface, "경고", "QGIS AuthManager를 사용할 수 없습니다. 키 저장에 실패했습니다.", level=1, duration=6)
        return None

    # Reuse existing config if present; otherwise create a new one.
    existing_id = str(_settings_get("authcfg", "") or "").strip()
    if existing_id:
        loaded = _load_auth_config(existing_id)
        if loaded is not None:
            auth_cfg = loaded

    try:
        auth_cfg.setName("ArchToolkit Gemini")
        auth_cfg.setMethod("Basic")
        auth_cfg.setConfig("username", "apikey")
        auth_cfg.setConfig("password", api_key)
    except Exception:
        if iface is not None:
            push_message(iface, "오류", "AuthManager 설정 구성 중 오류가 발생했습니다.", level=2, duration=6)
        return None

    ok = False
    try:
        if existing_id and getattr(auth_cfg, "id", lambda: "")() == existing_id:
            ok = _update_auth_config(auth_cfg)
        if not ok:
            ok = _store_auth_config(auth_cfg)
    except Exception:
        ok = False

    if not ok:
        if iface is not None:
            push_message(
                iface,
                "오류",
                "Gemini API 키를 AuthManager에 저장하지 못했습니다. (마스터 비밀번호 설정이 필요할 수 있습니다)",
                level=2,
                duration=8,
            )
        return None

    try:
        authcfg_id = str(auth_cfg.id() or "").strip()
    except Exception:
        authcfg_id = ""

    if authcfg_id:
        _settings_set("authcfg", authcfg_id)
        if iface is not None:
            push_message(iface, "완료", "Gemini API 키를 저장했습니다.", level=0, duration=5)

    return api_key


def generate_text(
    *,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float = 0.2,
    max_output_tokens: int = 1024,
    timeout_ms: int = 45000,
) -> Tuple[Optional[str], Optional[str]]:
    """Call Gemini generateContent and return (text, error_message)."""
    api_key = str(api_key or "").strip()
    if not api_key:
        return None, "API key is missing"

    model = normalize_model_name(model) or get_default_model_name()

    # API endpoint (Generative Language API)
    url = QUrl(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": str(prompt or "")}],
            }
        ],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max(64, min(8192, int(max_output_tokens)))),
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    try:
        from qgis.core import QgsNetworkAccessManager

        nam = QgsNetworkAccessManager.instance()
    except Exception:
        try:
            from qgis.PyQt.QtNetwork import QNetworkAccessManager

            nam = QNetworkAccessManager()
        except Exception:
            nam = None

    if nam is None:
        return None, "Network manager is unavailable"

    req = QNetworkRequest(url)
    req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json; charset=utf-8")

    try:
        reply = nam.post(req, data)
    except Exception as e:
        return None, f"Request failed: {e}"

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)

    def _on_timeout():
        try:
            reply.abort()
        except Exception:
            pass
        try:
            loop.quit()
        except Exception:
            pass

    def _on_finished():
        try:
            loop.quit()
        except Exception:
            pass

    try:
        timer.timeout.connect(_on_timeout)
        reply.finished.connect(_on_finished)
        timer.start(int(timeout_ms))
        loop.exec_()
    except Exception:
        pass

    try:
        if timer.isActive():
            timer.stop()
    except Exception:
        pass

    try:
        if reply.error():
            err = reply.errorString()
            try:
                body = bytes(reply.readAll()).decode("utf-8", "ignore")
            except Exception:
                body = ""
            return None, f"{err}\n{body}".strip()
    except Exception:
        pass

    try:
        raw = bytes(reply.readAll()).decode("utf-8", "ignore")
        obj = json.loads(raw) if raw else {}
    except Exception as e:
        return None, f"Invalid JSON response: {e}"

    # candidates[0].content.parts[0].text
    try:
        candidates = obj.get("candidates") or []
        if not candidates:
            return None, f"No candidates in response: {raw[:500]}"
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        texts = []
        for p in parts:
            t = p.get("text")
            if isinstance(t, str) and t.strip():
                texts.append(t.strip())
        if texts:
            return "\n".join(texts).strip(), None
        return None, f"No text parts in response: {raw[:500]}"
    except Exception as e:
        return None, f"Failed to parse response: {e}"


def explain_auth_manager_once() -> str:
    """User-facing short explanation about AuthManager persistence."""
    return (
        "네. 한 번 저장해두면(동일 QGIS 프로필 내) 다음부터는 authcfg id만 참조하므로 보통 다시 입력할 필요가 없습니다. "
        "다만 QGIS 인증 저장소(마스터 비밀번호)를 초기화/삭제하거나 다른 프로필을 쓰면 다시 설정해야 할 수 있습니다."
    )

