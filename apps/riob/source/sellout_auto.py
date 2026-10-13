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


def fontes_mensais_configuradas(environ):
    """Retorna todas as fontes mensais, mantendo compatibilidade com a fonte unica."""
    multiplas = str(environ.get('RB_SELLOUT_M_ARQUIVOS') or '').strip()
    if multiplas:
        fontes = [item.strip() for item in multiplas.split(os.pathsep) if item.strip()]
    else:
        unica = str(environ.get('RB_SELLOUT_M_ARQUIVO') or '').strip()
        fontes = [unica] if unica else [
            '/imports/sellout/IND3/SELLOUT_M.CSV',
            '/imports/sellout/INDB/SELLOUT_M.CSV',
        ]
    fontes_unicas = []
    caminhos = set()
    for fonte in fontes:
        caminho = os.path.realpath(fonte)
        if caminho not in caminhos:
            caminhos.add(caminho)
            fontes_unicas.append(fonte)
    if not fontes_unicas:
        raise ValueError('Nenhuma fonte SELLOUT mensal configurada.')
    return fontes_unicas


def unificar_mensais(fontes):
    """Valida e une bases completas, removendo duplicatas somente entre origens."""
    if not fontes:
        raise ValueError('Nenhuma fonte SELLOUT mensal informada.')
    fieldnames_referencia = None
    linhas_unificadas, periodos = [], set()
    fingerprints_anteriores = set()
    fontes_meta = []
    duplicadas_ignoradas = 0
    for indice, fonte in enumerate(fontes, 1):
        nome = str(fonte.get('nome') or f'fonte-{indice}')
        fieldnames = list(fonte.get('fieldnames') or [])
        if fieldnames_referencia is None:
            fieldnames_referencia = fieldnames
        elif fieldnames != fieldnames_referencia:
            raise ValueError(f'Cabecalho SELLOUT divergente na fonte {nome}.')
        mensal = preparar_mensal(fieldnames, fonte.get('rows') or [])
        fingerprints_fonte = set()
        linhas_fonte = 0
        linhas_incluidas = 0
        for row in mensal['rows']:
            linhas_fonte += 1
            fingerprint = tuple(str(row.get(campo) or '').strip() for campo in fieldnames_referencia)
            fingerprints_fonte.add(fingerprint)
            if fingerprint in fingerprints_anteriores:
                duplicadas_ignoradas += 1
                continue
            linhas_unificadas.append(row)
            linhas_incluidas += 1
        fingerprints_anteriores.update(fingerprints_fonte)
        for inicio, fim in mensal['periodos']:
            periodos.add((inicio, fim))
        fontes_meta.append({
            'nome': nome,
            'linhas': linhas_fonte,
            'linhas_incluidas': linhas_incluidas,
        })
    if not linhas_unificadas:
        raise ValueError('SELLOUT unificado vazio; base anterior preservada.')
    return {
        'fieldnames': fieldnames_referencia,
        'rows': linhas_unificadas,
        'periodos': sorted(periodos),
        'fontes': fontes_meta,
        'duplicadas_ignoradas': duplicadas_ignoradas,
    }


@contextmanager
def snapshots_estaveis(sources):
    """Copia todas as origens e valida que nenhuma mudou durante a leitura conjunta."""
    sources = list(sources or [])
    if not sources:
        raise ValueError('Nenhuma fonte SELLOUT mensal informada.')
    before = []
    for source in sources:
        stat = os.stat(source)
        if time.time() - stat.st_mtime < 60:
            raise ValueError(f'Arquivo {source} atualizado ha menos de um minuto; aguardando estabilizar.')
        before.append(stat)
    with tempfile.TemporaryDirectory(prefix='sellout-') as directory:
        snapshots = []
        assinatura = hashlib.sha256()
        for indice, (source, stat_inicial) in enumerate(zip(sources, before), 1):
            target = os.path.join(directory, f'SELLOUT_M_{indice}.CSV')
            shutil.copyfile(source, target)
            digest = hashlib.sha256()
            with open(target, 'rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            arquivo_hash = digest.hexdigest()
            snapshots.append({
                'source': source,
                'snapshot': target,
                'digest': arquivo_hash,
                'stat': stat_inicial,
            })
            assinatura.update(str(indice).encode('ascii'))
            assinatura.update(b'\0')
            assinatura.update(arquivo_hash.encode('ascii'))
            assinatura.update(b'\0')
        for source, stat_inicial, item in zip(sources, before, snapshots):
            stat_final = os.stat(source)
            if (stat_inicial.st_size, stat_inicial.st_mtime_ns) != (stat_final.st_size, stat_final.st_mtime_ns):
                raise ValueError(f'Arquivo {source} alterado durante a leitura; tentar novamente.')
            item['stat'] = stat_final
        yield snapshots, assinatura.hexdigest()


@contextmanager
def snapshot_estavel(source):
    """Uma copia temporaria por leitura, removida inclusive em caso de falha."""
    with snapshots_estaveis([source]) as (snapshots, _):
        item = snapshots[0]
        yield item['snapshot'], item['digest'], item['stat']


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
