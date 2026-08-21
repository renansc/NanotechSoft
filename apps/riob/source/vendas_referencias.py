import re
import unicodedata


def _texto(valor):
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def _chave(valor):
    texto = unicodedata.normalize("NFKD", _texto(valor))
    texto = "".join(char for char in texto if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", texto.casefold()).strip()


def valor_coluna(linha, *nomes):
    if not isinstance(linha, dict):
        return ""
    por_chave = {_chave(nome): valor for nome, valor in linha.items()}
    for nome in nomes:
        valor = por_chave.get(_chave(nome))
        if _texto(valor):
            return _texto(valor)
    return ""


def separar_codigo_nome(valor):
    texto = _texto(valor)
    if "-" not in texto:
        return "", texto
    codigo, nome = texto.split("-", 1)
    return _texto(codigo), _texto(nome)


def codigo_numerico(valor, largura=0):
    numeros = re.sub(r"\D+", "", _texto(valor))
    if not numeros:
        return ""
    numeros = str(int(numeros))
    return numeros.zfill(largura) if largura else numeros


def mapas_carga_equivalentes(mapa_pdf, mapas_sellout, vendedor_codigo):
    """Compara o mapa do PDF (vendedor+dia+sequencia) ao mapa final do SELLOUT."""
    mapa_pdf = re.sub(r"\D+", "", _texto(mapa_pdf))
    vendedor = codigo_numerico(vendedor_codigo)
    mapas = [
        re.sub(r"\D+", "", item)
        for item in re.split(r"\s*(?:,|\|)\s*", _texto(mapas_sellout))
        if re.sub(r"\D+", "", item)
    ]
    if len(mapas) != 1 or len(mapa_pdf) < 5 or len(mapas[0]) < 5 or not vendedor:
        return False
    prefixo_pdf = mapa_pdf[:-4].lstrip("0") or "0"
    return prefixo_pdf == vendedor.lstrip("0") and mapa_pdf[-4:] == mapas[0][-4:]


def normalizar_cliente(linha):
    vendedor_codigo, vendedor_nome = separar_codigo_nome(valor_coluna(linha, "VENDEDOR"))
    rota_original = valor_coluna(linha, "ROTA")
    codigo = valor_coluna(linha, "CODIGO", "CÓDIGO")
    if not codigo:
        return None
    rua = valor_coluna(linha, "RUA", "ENDERECO", "ENDEREÇO")
    numero = valor_coluna(linha, "NR", "NUMERO", "NÚMERO")
    endereco = ", ".join(parte for parte in (rua, numero) if parte)
    return {
        "codigo": codigo_numerico(codigo, 5),
        "rota_codigo": codigo_numerico(rota_original),
        "documento": re.sub(r"\D+", "", valor_coluna(linha, "CGC", "CNPJ", "CPF")),
        "razao_social": valor_coluna(linha, "RAZAO", "RAZÃO", "RAZ O"),
        "fantasia": valor_coluna(linha, "FANTASIA"),
        "endereco": endereco,
        "rua": rua,
        "numero": numero,
        "cidade": valor_coluna(linha, "CIDADE"),
        "uf": valor_coluna(linha, "UF"),
        "cep": re.sub(r"\D+", "", valor_coluna(linha, "CEP")),
        "bairro": valor_coluna(linha, "BAIRRO"),
        "vendedor_codigo": codigo_numerico(vendedor_codigo),
        "vendedor_nome": vendedor_nome,
        "status": valor_coluna(linha, "ESTATUS", "STATUS"),
    }


def _pdf_reader(path):
    from pypdf import PdfReader
    return PdfReader(path)


def parse_rotas_pdf(path):
    leitor = _pdf_reader(path)
    rotas = {}
    for pagina in leitor.pages:
        texto = pagina.extract_text(extraction_mode="layout") or ""
        for linha in texto.splitlines():
            match = re.match(r"^\s*(\d{1,5})\s+(.+?)\s*$", linha)
            if not match:
                continue
            codigo = codigo_numerico(match.group(1))
            descricao = _texto(match.group(2))
            if not codigo or not descricao or descricao.casefold().startswith("powered by"):
                continue
            rotas[codigo] = {
                "codigo": codigo,
                "descricao": descricao,
            }
    return [rotas[codigo] for codigo in sorted(rotas, key=lambda item: int(item))]


def classificar_etapa_conciliacao(tem_txt=False, tem_pdf=False, tem_sellout=False, divergencias=None):
    divergencias = list(divergencias or [])
    if tem_sellout:
        return {
            "etapa": 3,
            "status": "sellout_com_divergencias" if divergencias else "sellout_confirmado",
            "rotulo": "SELLOUT confirmado com alterações" if divergencias else "SELLOUT confirmado",
        }
    if tem_pdf:
        return {"etapa": 2, "status": "carga_pdf", "rotulo": "Carga PDF formada"}
    return {"etapa": 1, "status": "venda_txt", "rotulo": "Venda TXT recebida"}
