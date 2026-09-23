"""Cliente pequeno para os Correios Web Services (CWS).

Credenciais sao lidas exclusivamente do ambiente. O modulo cobre somente os
contratos usados pelo NanoStore: token por cartao de postagem, prazo nacional e
rastreamento de objetos. Ele nao compra etiqueta nem realiza postagem.
"""

import base64
from datetime import date, datetime, timedelta, timezone
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CorreiosError(RuntimeError):
    pass


def _digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _parse_date(value):
    raw = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _add_business_days(start, days):
    current = start
    remaining = max(int(days or 0), 0)
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


class CorreiosClient:
    def __init__(self, environ=None, timeout=15):
        env = os.environ if environ is None else environ
        self.base_url = str(env.get("NANOSTORE_CORREIOS_API_URL") or "https://api.correios.com.br").rstrip("/")
        self.username = str(env.get("NANOSTORE_CORREIOS_USERNAME") or "").strip()
        self.access_code = str(env.get("NANOSTORE_CORREIOS_ACCESS_CODE") or "").strip()
        self.posting_card = _digits(env.get("NANOSTORE_CORREIOS_POSTING_CARD"))
        self.origin_postal_code = _digits(env.get("NANOSTORE_CORREIOS_ORIGIN_POSTAL_CODE"))
        self.default_service_code = str(env.get("NANOSTORE_CORREIOS_SERVICE_CODE") or "").strip()
        self.timeout = timeout
        self._token = ""
        self._token_expires_at = None

    @property
    def configured(self):
        return bool(self.username and self.access_code and self.posting_card and self.origin_postal_code)

    def public_status(self):
        return {
            "configured": self.configured,
            "origin_postal_code": self.origin_postal_code,
            "default_service_code": self.default_service_code,
            "base_url": self.base_url,
        }

    def _request(self, method, path, *, body=None, query=None, token=False):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url += "?" + urlencode({key: value for key, value in query.items() if value not in (None, "")})
        headers = {"Accept": "application/json", "User-Agent": "NanoStore/1.0"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {self.token()}"
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read(4096).decode("utf-8", "replace"))
                detail = payload.get("msgs") or payload.get("message") or payload.get("erro") or ""
            except Exception:
                detail = ""
            raise CorreiosError(f"Correios CWS respondeu HTTP {exc.code}{': ' + str(detail) if detail else ''}.") from exc
        except (URLError, TimeoutError) as exc:
            raise CorreiosError("Nao foi possivel acessar os Correios CWS.") from exc
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorreiosError("Os Correios CWS retornaram uma resposta invalida.") from exc

    def token(self):
        now = datetime.now(timezone.utc)
        if self._token and self._token_expires_at and now < self._token_expires_at - timedelta(minutes=1):
            return self._token
        if not self.configured:
            raise CorreiosError("Configure as credenciais e o cartao de postagem dos Correios no ambiente.")
        credentials = base64.b64encode(f"{self.username}:{self.access_code}".encode()).decode()
        url = f"{self.base_url}/token/v1/autentica/cartaopostagem"
        request = Request(
            url,
            data=json.dumps({"numero": self.posting_card}).encode(),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {credentials}",
                "User-Agent": "NanoStore/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise CorreiosError(f"Nao foi possivel autenticar nos Correios CWS (HTTP {exc.code}).") from exc
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorreiosError("Nao foi possivel autenticar nos Correios CWS.") from exc
        token = str(payload.get("token") or "").strip()
        if not token:
            raise CorreiosError("Os Correios CWS nao retornaram token de acesso.")
        expires = payload.get("expiraEm") or payload.get("expiresAt") or payload.get("expiration")
        parsed_expiry = None
        if expires:
            try:
                parsed_expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                if parsed_expiry.tzinfo is None:
                    parsed_expiry = parsed_expiry.replace(tzinfo=timezone.utc)
            except ValueError:
                parsed_expiry = None
        self._token = token
        self._token_expires_at = parsed_expiry or (now + timedelta(minutes=30))
        return token

    def estimate_delivery(self, destination_postal_code, service_code=None, reference_date=None):
        destination = _digits(destination_postal_code)
        origin = self.origin_postal_code
        service = str(service_code or self.default_service_code or "").strip()
        if len(origin) != 8 or len(destination) != 8:
            raise CorreiosError("Informe CEP de origem e destino com 8 digitos.")
        if not service:
            raise CorreiosError("Informe o codigo do servico contratado nos Correios.")
        payload = self._request(
            "GET", f"prazo/v1/nacional/{service}", token=True,
            query={"cepOrigem": origin, "cepDestino": destination},
        )
        row = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(row, dict):
            raise CorreiosError("Os Correios nao retornaram uma previsao valida.")
        error = str(row.get("msgErro") or row.get("mensagem") or "").strip()
        if error and str(row.get("coErro") or row.get("erro") or "0") not in {"", "0"}:
            raise CorreiosError(error)
        days_raw = row.get("prazoEntrega") or row.get("prazo") or row.get("deliveryDays")
        try:
            business_days = int(days_raw)
        except (TypeError, ValueError):
            business_days = None
        maximum_date = _parse_date(row.get("dataMaxima") or row.get("dataPrevista") or row.get("estimatedDate"))
        reference = reference_date or date.today()
        if not maximum_date and business_days is not None:
            maximum_date = _add_business_days(reference, business_days)
        return {
            "service_code": service,
            "origin_postal_code": origin,
            "destination_postal_code": destination,
            "business_days": business_days,
            "estimated_delivery_date": maximum_date.isoformat() if maximum_date else "",
            "source": "correios_cws",
        }

    def track(self, tracking_code):
        code = str(tracking_code or "").strip().upper()
        if not code:
            raise CorreiosError("Informe o codigo de rastreio.")
        payload = self._request(
            "GET", f"srorastro/v1/objetos/{code}", token=True,
            query={"resultado": "T"},
        )
        objects = payload.get("objetos") if isinstance(payload, dict) else None
        obj = objects[0] if isinstance(objects, list) and objects else payload
        if not isinstance(obj, dict):
            raise CorreiosError("Os Correios nao retornaram dados para este objeto.")
        events = []
        for raw in obj.get("eventos") or []:
            if not isinstance(raw, dict):
                continue
            unit = raw.get("unidade") if isinstance(raw.get("unidade"), dict) else {}
            address = unit.get("endereco") if isinstance(unit.get("endereco"), dict) else {}
            occurred_at = _parse_datetime(raw.get("dtHrCriado") or raw.get("dataHora") or raw.get("date"))
            events.append({
                "code": str(raw.get("codigo") or raw.get("tipo") or "").strip(),
                "description": str(raw.get("descricao") or raw.get("mensagem") or "").strip(),
                "location": ", ".join(filter(None, [
                    str(unit.get("nome") or "").strip(),
                    str(address.get("cidade") or unit.get("cidade") or "").strip(),
                    str(address.get("uf") or unit.get("uf") or "").strip(),
                ])),
                "occurred_at": occurred_at.isoformat() + "Z" if occurred_at else "",
                "raw": raw,
            })
        return {
            "tracking_code": code,
            "events": events,
            "source": "correios_cws",
        }
