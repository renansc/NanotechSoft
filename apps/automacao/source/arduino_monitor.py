"""Read-only adapter for the Ethernet sensor station (/estado)."""
import datetime as dt
import ipaddress
import json
import math
import threading
import time
import urllib.request

SENSORS = [('rfid', 'RFID RC522'), ('touch', 'Touch'), ('infrared', 'Infravermelho TCRT5000'), ('distance', 'Distância HC-SR04')]
_lock = threading.Lock()
_cache = {}


def normalize(payload):
    if not isinstance(payload, dict) or not any(k in payload for k in ('rfidOk', 'touch', 'tcrtAtivo', 'distancia')):
        raise ValueError('Resposta não reconhecida como telemetria Arduino')

    def number(key):
        value = payload.get(key)
        return value if type(value) in (int, float) and math.isfinite(value) else None

    def sensor(key, label, status, value, unit='', detail=''):
        return dict(key=key, name=label, status=status, value=value, unit=unit, detail=detail)

    rfid = payload.get('rfidOk')
    touch = payload.get('touch')
    infrared = payload.get('tcrtAtivo')
    distance = number('distancia')
    count = number('contadorTCRT')
    uid = str(payload.get('ultimoUid') or 'nenhum')[:40]
    sensors = [
        sensor('rfid', 'RFID RC522', 'ok' if rfid is True else 'erro' if rfid is False else 'sem_dados',
               'Detectado' if rfid is True else 'Não detectado' if rfid is False else None, detail='Último UID: ' + uid),
        sensor('touch', 'Touch', 'ativo' if touch is True else 'ok' if touch is False else 'sem_dados',
               'Acionado' if touch is True else 'Em espera' if touch is False else None,
               detail='Estado da entrada digital; não comprova integridade elétrica.'),
        sensor('infrared', 'Infravermelho TCRT5000', 'ativo' if infrared is True else 'ok' if infrared is False else 'sem_dados',
               count if count is not None and count >= 0 else None, 'passagens',
               'Objeto detectado' if infrared is True else 'Livre' if infrared is False else 'Estado não informado'),
        sensor('distance', 'Distância HC-SR04', 'sem_leitura' if distance is None or distance < 0 else 'ativo' if distance <= 20 else 'ok',
               distance if distance is not None and distance >= 0 else None, 'cm',
               'Sem eco válido' if distance is None or distance < 0 else 'Objeto até 20 cm' if distance <= 20 else 'Livre'),
    ]
    readings = payload.get('leituras')
    readings = readings if isinstance(readings, list) else []
    return dict(sensors=sensors, readings=[dict(uid=str(r.get('uid', ''))[:40], name=str(r.get('nome', ''))[:80],
        epoch=r.get('epoch') if type(r.get('epoch')) is int and 0 < r['epoch'] < 4102444800 else None)
        for r in readings[:5] if isinstance(r, dict)], uptimeMs=number('uptimeMs'))


def unavailable(status, message):
    return dict(status=status, message=message, checkedAt=None, readings=[],
                sensors=[dict(key=k, name=n, status=status, value=None, unit='', detail='') for k, n in SENSORS])


def read_device(device):
    """Bounded local HTTP read, shared for one second; never follows redirects."""
    if not device.get('ativo'):
        return unavailable('inativo', 'Equipamento desativado no cadastro de Tecnologia.')
    host = str(device.get('host') or '')
    address = ipaddress.ip_address(host)
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
        raise ValueError('Arduino exige IPv4 privado da rede local')
    port = int(device.get('porta') or 80)
    if not 1 <= port <= 65535:
        raise ValueError('Porta inválida')
    key = (host, port)
    with _lock:
        previous = _cache.get(key)
        if previous and time.monotonic() - previous[0] < 1:
            return previous[1]
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(f'http://{host}:{port}/estado', timeout=2) as response:
                raw = response.read(8193)
            if len(raw) > 8192:
                raise ValueError('Resposta excede 8 KB')
            result = normalize(json.loads(raw))
            result.update(status='online', message='Comunicação ativa')
        except (OSError, ValueError, UnicodeError):
            result = unavailable('indisponivel', 'Sem telemetria válida do Arduino; verifique rede e alimentação.')
        result['checkedAt'] = dt.datetime.now(dt.UTC).isoformat()
        _cache.clear()
        _cache[key] = (time.monotonic(), result)
        return result
