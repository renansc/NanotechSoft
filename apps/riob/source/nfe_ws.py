import base64
import datetime
import gzip
import os
import tempfile
import time
import zlib
from contextlib import contextmanager
import xml.etree.ElementTree as ET

try:
    import requests
except Exception:  # pragma: no cover - dependencia opcional
    requests = None

try:
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
except Exception:  # pragma: no cover - dependencia opcional
    Encoding = None
    NoEncryption = None
    PrivateFormat = None
    pkcs12 = None

try:
    from lxml import etree
except Exception:  # pragma: no cover - dependencia opcional
    etree = None

try:
    from signxml import XMLSigner, methods
except Exception:  # pragma: no cover - dependencia opcional
    XMLSigner = None
    methods = None


class LegacyXMLSigner(XMLSigner if XMLSigner is not None else object):
    """Permite SHA-1 apenas para o fluxo legado exigido pela SEFAZ NF-e."""

    def check_deprecated_methods(self):  # pragma: no cover - depende da lib externa
        return None


AMBIENTE_PRODUCAO = "producao"
AMBIENTE_HOMOLOGACAO = "homologacao"

URLS = {
    AMBIENTE_PRODUCAO: {
        "distribuicao": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
        "evento": "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    },
    AMBIENTE_HOMOLOGACAO: {
        "distribuicao": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
        "evento": "https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    },
}

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
NFE_NS = "http://www.portalfiscal.inf.br/nfe"
WSDL_DIST_NS = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
WSDL_EVENTO_NS = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4"

MANIFESTOS = {
    "ciencia": {"codigo": "210210", "descricao": "Ciencia da Operacao", "justificativa": False},
    "confirmacao": {"codigo": "210200", "descricao": "Confirmacao da Operacao", "justificativa": False},
    "desconhecimento": {"codigo": "210220", "descricao": "Desconhecimento da Operacao", "justificativa": False},
    "nao_realizada": {"codigo": "210240", "descricao": "Operacao nao Realizada", "justificativa": True},
}


def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _normalize_cnpj(value):
    return _digits_only(value)


def _normalize_chave(value):
    return _digits_only(value)


def _normalize_nsu(value):
    digits = _digits_only(value)
    if not digits:
        return ""
    return digits.zfill(15)


def _xml_local_name(tag):
    tag = str(tag or "")
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _xml_find_first(node, local_name):
    if node is None:
        return None
    for child in node.iter():
        if _xml_local_name(child.tag) == local_name:
            return child
    return None


def _xml_find_all(node, local_name):
    if node is None:
        return []
    return [child for child in node.iter() if _xml_local_name(child.tag) == local_name]


def _xml_text(node, local_name, default=""):
    found = _xml_find_first(node, local_name)
    if found is None or found.text is None:
        return default
    return str(found.text).strip()


def _decode_doczip(doczip_text):
    payload = base64.b64decode((doczip_text or "").encode("utf-8"))
    attempts = []
    try:
        attempts.append(gzip.decompress(payload))
    except Exception:
        pass
    for wbits in (zlib.MAX_WBITS | 16, zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            attempts.append(zlib.decompress(payload, wbits))
        except Exception:
            pass
    for content in attempts:
        if content:
            try:
                return content.decode("utf-8-sig")
            except Exception:
                return content.decode("latin-1", errors="ignore")
    raise RuntimeError("Nao foi possivel descompactar o docZip retornado pela SEFAZ.")


def _envia_soap(url, soap_action_candidates, envelope_xml, cert_path, key_path, timeout=30):
    _require_http_crypto("transmissao SOAP NF-e")
    last_response = None
    last_error = None
    action_candidates = list(soap_action_candidates or [])
    if "" not in action_candidates:
        action_candidates.append("")
    for action in action_candidates:
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
        }
        if action:
            headers["SOAPAction"] = f"\"{action}\""
        try:
            resp = requests.post(
                url,
                data=envelope_xml.encode("utf-8"),
                headers=headers,
                cert=(cert_path, key_path),
                timeout=timeout,
            )
        except Exception as exc:
            last_error = exc
            continue
        last_response = resp
        body_text = resp.text or ""
        if resp.status_code < 500:
            return resp
        if "SOAPAction" not in body_text and "soapaction" not in body_text.lower():
            return resp
    if last_response is not None:
        return last_response
    raise RuntimeError(f"Falha ao conectar no Web Service da NF-e: {last_error}")


def _parse_soap_body(xml_text):
    try:
        return ET.fromstring(xml_text)
    except Exception as exc:
        raise RuntimeError(f"Resposta XML invalida da SEFAZ: {exc}") from exc


def _extract_soap_fault_text(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""

    fault = _xml_find_first(root, "Fault")
    if fault is not None:
        for field in ("faultstring", "Text", "Reason", "detail"):
            value = _xml_text(fault, field)
            if value:
                return value

    ret_evento = _xml_find_first(root, "retEnvEvento")
    if ret_evento is not None:
        c_stat = _xml_text(ret_evento, "cStat")
        x_motivo = _xml_text(ret_evento, "xMotivo")
        inf = _xml_find_first(ret_evento, "infEvento")
        inf_c_stat = _xml_text(inf, "cStat")
        inf_x_motivo = _xml_text(inf, "xMotivo")
        detail = " | ".join(
            part for part in (
                f"Lote {c_stat}: {x_motivo}" if c_stat or x_motivo else "",
                f"Evento {inf_c_stat}: {inf_x_motivo}" if inf_c_stat or inf_x_motivo else "",
            ) if part
        )
        if detail:
            return detail

    ret_dist = _xml_find_first(root, "retDistDFeInt")
    if ret_dist is not None:
        c_stat = _xml_text(ret_dist, "cStat")
        x_motivo = _xml_text(ret_dist, "xMotivo")
        if c_stat or x_motivo:
            return f"{c_stat}: {x_motivo}".strip(": ")

    return ""


def _build_http_error_message(service_name, response, parse_error=None):
    status = getattr(response, "status_code", "")
    reason = getattr(response, "reason", "") or ""
    body_text = getattr(response, "text", "") or ""
    detail = _extract_soap_fault_text(body_text)
    if not detail and parse_error is not None:
        detail = str(parse_error)
    if not detail and body_text:
        compact = " ".join(str(body_text).split())
        if compact:
            detail = compact[:280]

    message = f"Falha HTTP no {service_name}: {status} {reason}".strip()
    if detail:
        message += f". Detalhe: {detail}"
    return message


def _log_http_failure(service_name, response):
    try:
        status = getattr(response, "status_code", "")
        reason = getattr(response, "reason", "") or ""
        body_text = getattr(response, "text", "") or ""
        compact = " ".join(str(body_text).split())
        if len(compact) > 1200:
            compact = compact[:1200] + "...[truncado]"
        print(f"{service_name} HTTP failure: status={status} reason={reason} body={compact}")
    except Exception:
        pass


def _parse_dist_response(xml_text):
    root = _parse_soap_body(xml_text)
    ret = _xml_find_first(root, "retDistDFeInt")
    if ret is None:
        fault = _xml_find_first(root, "Fault")
        if fault is not None:
            fault_text = _xml_text(fault, "faultstring") or _xml_text(fault, "Reason")
            raise RuntimeError(f"Falha SOAP no NFeDistribuicaoDFe: {fault_text or 'erro nao informado'}")
        raise RuntimeError("Nao foi encontrado retDistDFeInt na resposta da SEFAZ.")

    documentos = []
    for doc in _xml_find_all(ret, "docZip"):
        try:
            xml_doc = _decode_doczip(doc.text or "")
        except Exception as exc:
            xml_doc = ""
            erro_doc = str(exc)
        else:
            erro_doc = ""

        root_type = ""
        chave = ""
        if xml_doc:
            try:
                doc_root = ET.fromstring(xml_doc)
                root_type = _xml_local_name(doc_root.tag)
                chave = _xml_text(doc_root, "chNFe")
                if not chave:
                    inf_nfe = _xml_find_first(doc_root, "infNFe")
                    if inf_nfe is not None:
                        raw_id = str((inf_nfe.attrib or {}).get("Id", ""))
                        if raw_id.startswith("NFe"):
                            chave = raw_id[3:]
            except Exception:
                pass

        documentos.append({
            "nsu": _normalize_nsu((doc.attrib or {}).get("NSU") or (doc.attrib or {}).get("nsu")),
            "schema": str((doc.attrib or {}).get("schema", "")).strip(),
            "xml_text": xml_doc,
            "erro_doczip": erro_doc,
            "root_type": root_type,
            "chave_acesso": _normalize_chave(chave),
        })

    return {
        "tp_amb": _xml_text(ret, "tpAmb"),
        "ver_aplic": _xml_text(ret, "verAplic"),
        "c_stat": _xml_text(ret, "cStat"),
        "x_motivo": _xml_text(ret, "xMotivo"),
        "dh_resp": _xml_text(ret, "dhResp"),
        "ult_nsu": _normalize_nsu(_xml_text(ret, "ultNSU")),
        "max_nsu": _normalize_nsu(_xml_text(ret, "maxNSU")),
        "lote_dist_dfe_int": _xml_text(ret, "loteDistDFeInt"),
        "documentos": documentos,
        "raw_response_xml": xml_text,
    }


def _parse_evento_response(xml_text):
    root = _parse_soap_body(xml_text)
    ret = _xml_find_first(root, "retEnvEvento")
    if ret is None:
        fault = _xml_find_first(root, "Fault")
        if fault is not None:
            fault_text = _xml_text(fault, "faultstring") or _xml_text(fault, "Reason")
            raise RuntimeError(f"Falha SOAP no RecepcaoEvento: {fault_text or 'erro nao informado'}")
        raise RuntimeError("Nao foi encontrado retEnvEvento na resposta da SEFAZ.")

    ret_evento = _xml_find_first(ret, "retEvento")
    inf = _xml_find_first(ret_evento, "infEvento") if ret_evento is not None else None
    return {
        "c_stat_lote": _xml_text(ret, "cStat"),
        "x_motivo_lote": _xml_text(ret, "xMotivo"),
        "tp_amb": _xml_text(ret, "tpAmb"),
        "ver_aplic": _xml_text(ret, "verAplic"),
        "c_stat": _xml_text(inf, "cStat"),
        "x_motivo": _xml_text(inf, "xMotivo"),
        "chave_acesso": _normalize_chave(_xml_text(inf, "chNFe")),
        "tp_evento": _xml_text(inf, "tpEvento"),
        "n_seq_evento": _xml_text(inf, "nSeqEvento"),
        "n_prot": _xml_text(inf, "nProt"),
        "dh_reg_evento": _xml_text(inf, "dhRegEvento"),
        "raw_response_xml": xml_text,
    }


def _require_http_crypto(feature_name):
    missing = []
    if requests is None:
        missing.append("requests")
    if pkcs12 is None:
        missing.append("cryptography")
    if missing:
        raise RuntimeError(
            f"O recurso '{feature_name}' exige as dependencias Python: {', '.join(missing)}. "
            "Atualize o ambiente com o requirements.txt antes de usar a integracao DF-e."
        )


def _require_evento_dependencies(feature_name):
    _require_http_crypto(feature_name)
    missing = []
    if etree is None:
        missing.append("lxml")
    if XMLSigner is None or methods is None:
        missing.append("signxml")
    if missing:
        raise RuntimeError(
            f"O recurso '{feature_name}' exige as dependencias Python: {', '.join(missing)}. "
            "Atualize o ambiente com o requirements.txt antes de usar a integracao DF-e."
        )


@contextmanager
def _pkcs12_temp_pem_files(certificado_arquivo, certificado_senha):
    _require_http_crypto("certificado digital A1")
    if not os.path.exists(certificado_arquivo):
        raise RuntimeError("Arquivo de certificado digital nao encontrado.")

    with open(certificado_arquivo, "rb") as f:
        pfx_bytes = f.read()
    password_bytes = None
    if certificado_senha not in (None, ""):
        password_bytes = str(certificado_senha).encode("utf-8")
    try:
        key, cert, chain = pkcs12.load_key_and_certificates(pfx_bytes, password_bytes)
    except Exception as exc:
        raise RuntimeError(f"Nao foi possivel abrir o certificado digital: {exc}") from exc

    if key is None or cert is None:
        raise RuntimeError("O certificado digital informado nao contem chave privada utilizavel.")

    fd_key, path_key = tempfile.mkstemp(prefix="riobranco-nfe-key-", suffix=".pem")
    fd_cert, path_cert = tempfile.mkstemp(prefix="riobranco-nfe-cert-", suffix=".pem")
    try:
        with os.fdopen(fd_key, "wb") as f_key:
            f_key.write(
                key.private_bytes(
                    encoding=Encoding.PEM,
                    format=PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=NoEncryption(),
                )
            )
        with os.fdopen(fd_cert, "wb") as f_cert:
            f_cert.write(cert.public_bytes(Encoding.PEM))
            for extra in chain or []:
                f_cert.write(extra.public_bytes(Encoding.PEM))
        yield path_cert, path_key
    finally:
        for path in (path_key, path_cert):
            try:
                os.remove(path)
            except Exception:
                pass


def _build_dist_envelope(cnpj, cuf_autor, tp_amb, ult_nsu="", chave_acesso=""):
    cnpj = _normalize_cnpj(cnpj)
    chave_acesso = _normalize_chave(chave_acesso)
    ult_nsu = _normalize_nsu(ult_nsu) or "000000000000000"
    if len(cnpj) != 14:
        raise RuntimeError("O CNPJ do destinatario precisa ter 14 digitos para consultar o DF-e.")
    if len(str(cuf_autor or "").strip()) == 0:
        raise RuntimeError("Informe a UF autora da consulta para usar o DF-e.")

    if chave_acesso:
        operacao_xml = f"""
      <consChNFe>
        <chNFe>{chave_acesso}</chNFe>
      </consChNFe>"""
    else:
        operacao_xml = f"""
      <distNSU>
        <ultNSU>{ult_nsu}</ultNSU>
      </distNSU>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{SOAP_NS}">
  <soap:Header>
    <nfeCabecMsg xmlns="{WSDL_DIST_NS}">
      <cUF>{cuf_autor}</cUF>
      <versaoDados>1.01</versaoDados>
    </nfeCabecMsg>
  </soap:Header>
  <soap:Body>
    <nfeDistDFeInteresse xmlns="{WSDL_DIST_NS}">
      <nfeDadosMsg xmlns="{WSDL_DIST_NS}">
        <distDFeInt xmlns="{NFE_NS}" versao="1.01">
          <tpAmb>{tp_amb}</tpAmb>
          <cUFAutor>{cuf_autor}</cUFAutor>
          <CNPJ>{cnpj}</CNPJ>{operacao_xml}
        </distDFeInt>
      </nfeDadosMsg>
    </nfeDistDFeInteresse>
  </soap:Body>
</soap:Envelope>
"""


def consultar_distribuicao(cnpj, certificado_arquivo, certificado_senha, ambiente=AMBIENTE_PRODUCAO, cuf_autor="12", ult_nsu="", chave_acesso="", timeout=30):
    ambiente = AMBIENTE_HOMOLOGACAO if str(ambiente or "").strip().lower() == AMBIENTE_HOMOLOGACAO else AMBIENTE_PRODUCAO
    tp_amb = "2" if ambiente == AMBIENTE_HOMOLOGACAO else "1"
    envelope_xml = _build_dist_envelope(
        cnpj=cnpj,
        cuf_autor=str(cuf_autor or "").strip(),
        tp_amb=tp_amb,
        ult_nsu=ult_nsu,
        chave_acesso=chave_acesso,
    )
    with _pkcs12_temp_pem_files(certificado_arquivo, certificado_senha) as (cert_path, key_path):
        resp = _envia_soap(
            URLS[ambiente]["distribuicao"],
            [
                f"{WSDL_DIST_NS}/nfeDistDFeInteresse",
            ],
            envelope_xml,
            cert_path=cert_path,
            key_path=key_path,
            timeout=timeout,
        )
    if not resp.ok:
        _log_http_failure("NFeDistribuicaoDFe", resp)
        try:
            return _parse_dist_response(resp.text)
        except Exception as exc:
            raise RuntimeError(_build_http_error_message("NFeDistribuicaoDFe", resp, exc)) from exc
    return _parse_dist_response(resp.text)


def _assinar_evento_xml(evento_element, reference_uri, cert_pem_text, key_pem_text):
    signer_cls = LegacyXMLSigner if XMLSigner is not None else None
    signer = signer_cls(
        method=methods.enveloped,
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    return signer.sign(
        evento_element,
        key=key_pem_text,
        cert=cert_pem_text,
        reference_uri=reference_uri,
        always_add_key_value=False,
    )


def _agora_brasilia_iso():
    tz = datetime.timezone(datetime.timedelta(hours=-3))
    return datetime.datetime.now(tz).replace(microsecond=0).isoformat()


def _build_env_evento(chave_acesso, cnpj, tp_amb, tipo_manifesto="ciencia", sequencia=1, justificativa=""):
    manifesto = MANIFESTOS.get(str(tipo_manifesto or "").strip().lower())
    if not manifesto:
        raise RuntimeError("Tipo de manifestacao invalido.")

    if len(_normalize_chave(chave_acesso)) != 44:
        raise RuntimeError("A chave de acesso da NF-e precisa ter 44 digitos para manifestar.")
    cnpj = _normalize_cnpj(cnpj)
    if len(cnpj) != 14:
        raise RuntimeError("O CNPJ do destinatario precisa ter 14 digitos para manifestar.")

    if etree is None:
        raise RuntimeError("lxml nao esta disponivel para gerar o evento da NF-e.")

    env = etree.Element(f"{{{NFE_NS}}}envEvento", versao="1.00", nsmap={None: NFE_NS})
    etree.SubElement(env, f"{{{NFE_NS}}}idLote").text = str(int(time.time() * 1000))[-15:].zfill(15)
    evento = etree.SubElement(env, f"{{{NFE_NS}}}evento", versao="1.00")
    evento_id = f"ID{manifesto['codigo']}{_normalize_chave(chave_acesso)}{int(sequencia):02d}"
    inf = etree.SubElement(evento, f"{{{NFE_NS}}}infEvento", Id=evento_id)
    etree.SubElement(inf, f"{{{NFE_NS}}}cOrgao").text = "91"
    etree.SubElement(inf, f"{{{NFE_NS}}}tpAmb").text = tp_amb
    etree.SubElement(inf, f"{{{NFE_NS}}}CNPJ").text = cnpj
    etree.SubElement(inf, f"{{{NFE_NS}}}chNFe").text = _normalize_chave(chave_acesso)
    etree.SubElement(inf, f"{{{NFE_NS}}}dhEvento").text = _agora_brasilia_iso()
    etree.SubElement(inf, f"{{{NFE_NS}}}tpEvento").text = manifesto["codigo"]
    etree.SubElement(inf, f"{{{NFE_NS}}}nSeqEvento").text = str(int(sequencia))
    etree.SubElement(inf, f"{{{NFE_NS}}}verEvento").text = "1.00"
    det = etree.SubElement(inf, f"{{{NFE_NS}}}detEvento", versao="1.00")
    etree.SubElement(det, f"{{{NFE_NS}}}descEvento").text = manifesto["descricao"]
    if manifesto["justificativa"]:
        just = str(justificativa or "").strip()
        if len(just) < 15:
            raise RuntimeError("A operacao nao realizada exige justificativa com pelo menos 15 caracteres.")
        etree.SubElement(det, f"{{{NFE_NS}}}xJust").text = just[:255]
    return env, evento_id


def _build_evento_envelope(evento_assinado_xml):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{SOAP_NS}">
  <soap:Header>
    <nfeCabecMsg xmlns="{WSDL_EVENTO_NS}">
      <cUF>91</cUF>
      <versaoDados>1.00</versaoDados>
    </nfeCabecMsg>
  </soap:Header>
  <soap:Body>
    <nfeRecepcaoEventoNF xmlns="{WSDL_EVENTO_NS}">
      <nfeDadosMsg xmlns="{WSDL_EVENTO_NS}">{evento_assinado_xml}</nfeDadosMsg>
    </nfeRecepcaoEventoNF>
  </soap:Body>
</soap:Envelope>
"""


def manifestar_nfe(chave_acesso, cnpj, certificado_arquivo, certificado_senha, ambiente=AMBIENTE_PRODUCAO, tipo_manifesto="ciencia", sequencia=1, justificativa="", timeout=30):
    ambiente = AMBIENTE_HOMOLOGACAO if str(ambiente or "").strip().lower() == AMBIENTE_HOMOLOGACAO else AMBIENTE_PRODUCAO
    tp_amb = "2" if ambiente == AMBIENTE_HOMOLOGACAO else "1"
    _require_evento_dependencies("manifestacao do destinatario")

    env, evento_id = _build_env_evento(
        chave_acesso=chave_acesso,
        cnpj=cnpj,
        tp_amb=tp_amb,
        tipo_manifesto=tipo_manifesto,
        sequencia=sequencia,
        justificativa=justificativa,
    )

    with _pkcs12_temp_pem_files(certificado_arquivo, certificado_senha) as (cert_path, key_path):
        with open(cert_path, "r", encoding="utf-8") as f_cert:
            cert_pem = f_cert.read()
        with open(key_path, "r", encoding="utf-8") as f_key:
            key_pem = f_key.read()
        evento = env.find(f"{{{NFE_NS}}}evento")
        signed_evento = _assinar_evento_xml(
            evento_element=evento,
            reference_uri=f"#{evento_id}",
            cert_pem_text=cert_pem,
            key_pem_text=key_pem,
        )
        env.replace(evento, signed_evento)
        evento_xml = etree.tostring(env, encoding="unicode")
        envelope_xml = _build_evento_envelope(evento_xml)
        resp = _envia_soap(
            URLS[ambiente]["evento"],
            [
                f"{WSDL_EVENTO_NS}/nfeRecepcaoEventoNF",
                f"{WSDL_EVENTO_NS}/nfeRecepcaoEvento",
            ],
            envelope_xml,
            cert_path=cert_path,
            key_path=key_path,
            timeout=timeout,
        )
    if not resp.ok:
        _log_http_failure("RecepcaoEvento", resp)
        try:
            return _parse_evento_response(resp.text)
        except Exception as exc:
            raise RuntimeError(_build_http_error_message("RecepcaoEvento", resp, exc)) from exc
    return _parse_evento_response(resp.text)


def localizar_xml_nfe(documentos):
    for doc in documentos or []:
        root_type = str(doc.get("root_type") or "").strip()
        schema = str(doc.get("schema") or "").strip().lower()
        if root_type in ("nfeProc", "procNFe", "NFe"):
            return doc
        if "procnfe" in schema or schema.startswith("nfe_v"):
            return doc
    return None


def buscar_nfe_por_chave(chave_acesso, cnpj, certificado_arquivo, certificado_senha, ambiente=AMBIENTE_PRODUCAO, cuf_autor="12", manifestar_automaticamente=True, timeout=30, tentativas_manifestacao=3, espera_manifestacao_segundos=3):
    chave_acesso = _normalize_chave(chave_acesso)
    if len(chave_acesso) != 44:
        raise RuntimeError("A chave de acesso da NF-e precisa ter 44 digitos.")

    consulta = consultar_distribuicao(
        cnpj=cnpj,
        certificado_arquivo=certificado_arquivo,
        certificado_senha=certificado_senha,
        ambiente=ambiente,
        cuf_autor=cuf_autor,
        chave_acesso=chave_acesso,
        timeout=timeout,
    )
    documento = localizar_xml_nfe(consulta.get("documentos"))
    manifestacao = None

    if documento and documento.get("xml_text"):
        return {
            "consulta": consulta,
            "manifestacao": None,
            "documento": documento,
            "xml_text": documento.get("xml_text"),
            "manifestado": False,
        }

    if not manifestar_automaticamente:
        return {
            "consulta": consulta,
            "manifestacao": None,
            "documento": documento,
            "xml_text": "",
            "manifestado": False,
        }

    manifestacao = manifestar_nfe(
        chave_acesso=chave_acesso,
        cnpj=cnpj,
        certificado_arquivo=certificado_arquivo,
        certificado_senha=certificado_senha,
        ambiente=ambiente,
        tipo_manifesto="ciencia",
        timeout=timeout,
    )

    for tentativa in range(max(int(tentativas_manifestacao), 1)):
        if tentativa > 0 and espera_manifestacao_segundos > 0:
            time.sleep(float(espera_manifestacao_segundos))
        consulta = consultar_distribuicao(
            cnpj=cnpj,
            certificado_arquivo=certificado_arquivo,
            certificado_senha=certificado_senha,
            ambiente=ambiente,
            cuf_autor=cuf_autor,
            chave_acesso=chave_acesso,
            timeout=timeout,
        )
        documento = localizar_xml_nfe(consulta.get("documentos"))
        if documento and documento.get("xml_text"):
            break

    return {
        "consulta": consulta,
        "manifestacao": manifestacao,
        "documento": documento,
        "xml_text": (documento or {}).get("xml_text") or "",
        "manifestado": True,
    }
