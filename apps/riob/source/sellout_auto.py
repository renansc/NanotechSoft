"""Leitura do consolidado mensal CTA, sem inferir datas de notas ausentes."""
import csv
import datetime
import hashlib
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager


def proxima_leitura_diaria(now):
    """Proxima passagem as 08:00 no fuso do instante informado, sem carga no startup."""
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def preparar_mensal(fieldnames, rows, preservar_datas=False):
    if not {'Mes&Ano', 'Cliente', 'Produto', 'Quantidade', 'Valor Venda'}.issubset(fieldnames or []):
        raise ValueError('Cabecalho SELLOUT mensal incompleto.')
    preparadas, competencias = [], set()
    for numero, original in enumerate(rows, 2):
        if None in original or any(value is None for value in original.values()):
            raise ValueError(f'Linha {numero} incompleta ou com colunas extras.')
        row = dict(original)
        match = re.fullmatch(r'\s*(\d{1,2})/\s*(\d{4})\s*', row['Mes&Ano'])
        if not match:
            raise ValueError(f'Competencia mensal invalida na linha {numero}.')
        inicio = datetime.date(int(match[2]), int(match[1]), 1)
        if not 2000 <= inicio.year <= 2100:
            raise ValueError(f'Ano invalido na linha {numero}.')
        if preservar_datas:
            texto = str(row.get('Data') or '').strip()
            if any(c.isdigit() for c in texto):
                try:
                    data_real = datetime.datetime.strptime(texto, '%d/%m/%Y').date()
                except ValueError as exc:
                    raise ValueError(f'Data invalida na linha {numero}.') from exc
                if data_real.replace(day=1) != inicio:
                    raise ValueError(f'Data diverge da competencia na linha {numero}.')
                row['_data_real'] = data_real
        row['_competencia'] = inicio
        preparadas.append(row)
        competencias.add(inicio)
    if not preparadas:
        raise ValueError('SELLOUT vazio; base anterior preservada.')
    return {
        'fieldnames': fieldnames,
        'rows': preparadas,
        'periodos': [(inicio, (inicio.replace(day=28) + datetime.timedelta(days=4)).replace(day=1))
                     for inicio in sorted(competencias)],
    }


@contextmanager
def snapshot_estavel(source):
    """Uma copia temporaria por leitura, removida inclusive em caso de falha."""
    before = os.stat(source)
    if time.time() - before.st_mtime < 60:
        raise ValueError('Arquivo atualizado ha menos de um minuto; aguardando estabilizar.')
    with tempfile.TemporaryDirectory(prefix='sellout-') as directory:
        target = os.path.join(directory, 'SELLOUT_M.CSV')
        shutil.copyfile(source, target)
        after = os.stat(source)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Arquivo alterado durante a leitura; tentar novamente.')
        digest = hashlib.sha256()
        with open(target, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        yield target, digest.hexdigest(), after


@contextmanager
def particionar_historico(fieldnames, rows):
    """Valida toda a fonte e separa meses em disco antes de qualquer gravacao SQL."""
    with tempfile.TemporaryDirectory(prefix='sellout-historico-') as directory:
        arquivos, writers, contagens = {}, {}, {}
        try:
            for raw in rows:
                row = preparar_mensal(fieldnames, [raw], preservar_datas=True)['rows'][0]
                mes = row['_competencia']
                if mes not in arquivos:
                    path = os.path.join(directory, mes.isoformat() + '.csv')
                    arquivos[mes] = open(path, 'w', encoding='utf-8', newline='')
                    writers[mes] = csv.DictWriter(arquivos[mes], fieldnames=fieldnames, delimiter=';')
                    writers[mes].writeheader()
                    contagens[mes] = 0
                writers[mes].writerow(raw)
                contagens[mes] += 1
        finally:
            for handle in arquivos.values():
                handle.close()
        if not arquivos:
            raise ValueError('Historico vazio.')
        yield [(mes, arquivos[mes].name, contagens[mes]) for mes in sorted(arquivos)]
