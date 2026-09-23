"""Catalogo e normalizacao do hub omnichannel do NanoStore.

Este modulo nao guarda credenciais e nao faz chamadas externas por conta
propria. Ele descreve o contrato de cada canal e normaliza os nomes usados no
banco e nas APIs internas. Adaptadores nativos podem consumir o mesmo contrato
sem misturar regras especificas de marketplace com estoque e vendas.
"""

import re


MARKETPLACE_CHANNELS = {
    "woocommerce": {
        "label": "WordPress / WooCommerce",
        "connection_mode": "direct_api",
        "access_label": "API REST e webhooks da loja",
        "capabilities": ["orders", "catalog", "inventory", "webhooks"],
        "official_docs": "https://developer.woocommerce.com/docs/apis/rest-api/",
        "notes": "A logistica depende do transportador ou plugin instalado no WooCommerce.",
    },
    "shopee": {
        "label": "Shopee",
        "connection_mode": "partner_api",
        "access_label": "Shopee Open Platform",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://open.shopee.com/",
        "notes": "Exige aplicativo e autorizacao da conta vendedora na Open Platform.",
    },
    "mercado_livre": {
        "label": "Mercado Livre",
        "connection_mode": "partner_api",
        "access_label": "Developers Mercado Livre",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://developers.mercadolivre.com.br/",
        "notes": "Exige OAuth, seller autorizado e notificacoes configuradas.",
    },
    "ifood": {
        "label": "iFood",
        "connection_mode": "partner_api",
        "access_label": "Portal do Desenvolvedor iFood",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://developer.ifood.com.br/",
        "notes": "O acesso depende do produto contratado e da homologacao do integrador.",
    },
    "aiqfome": {
        "label": "aiqfome",
        "connection_mode": "restricted_partner",
        "access_label": "Integracao comercial/homologada",
        "capabilities": ["orders", "catalog", "webhooks"],
        "official_docs": "https://aiqfome.com/",
        "notes": "Usa conector homologado ou relay canonico quando nao houver API publica para a conta.",
    },
    "magalu": {
        "label": "Magazine Luiza / Magalu",
        "connection_mode": "partner_api",
        "access_label": "API de parceiros Magalu",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://developers.magalu.com/",
        "notes": "Exige cadastro e credenciais do seller ou integrador homologado.",
    },
    "amazon": {
        "label": "Amazon",
        "connection_mode": "partner_api",
        "access_label": "Selling Partner API (SP-API)",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://developer-docs.amazon.com/sp-api/",
        "notes": "Exige aplicacao SP-API, OAuth e permissoes por regiao/conta.",
    },
    "facebook_marketplace": {
        "label": "Facebook Marketplace",
        "connection_mode": "restricted_partner",
        "access_label": "Meta Commerce para contas elegiveis",
        "capabilities": ["catalog", "orders", "webhooks"],
        "official_docs": "https://developers.facebook.com/docs/commerce-platform/",
        "notes": "Pedidos e checkout dependem da elegibilidade e do produto Meta disponivel para a conta.",
    },
    "whatsapp": {
        "label": "WhatsApp Business",
        "connection_mode": "conversational",
        "access_label": "WhatsApp Business Platform",
        "capabilities": ["orders", "catalog", "messages", "webhooks"],
        "official_docs": "https://developers.facebook.com/docs/whatsapp/cloud-api/",
        "notes": "Centraliza pedidos conversacionais; entrega continua no fluxo logistico do NanoStore.",
    },
    "aliexpress": {
        "label": "AliExpress",
        "connection_mode": "partner_api",
        "access_label": "AliExpress Open Platform",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://open.aliexpress.com/",
        "notes": "Exige aplicativo e autorizacao do seller na regiao atendida.",
    },
    "olx": {
        "label": "OLX",
        "connection_mode": "classifieds_partner",
        "access_label": "API/parceria conforme vertical",
        "capabilities": ["catalog", "leads", "webhooks"],
        "official_docs": "https://developers.olx.com.br/",
        "notes": "Classificados e leads nao equivalem sempre a pedido, estoque e logistica transacionais.",
    },
    "ebay": {
        "label": "eBay",
        "connection_mode": "partner_api",
        "access_label": "Sell APIs",
        "capabilities": ["orders", "catalog", "inventory", "logistics", "webhooks"],
        "official_docs": "https://developer.ebay.com/api-docs/sell/static/overview.html",
        "notes": "Exige OAuth e politicas comerciais/logisticas configuradas na conta.",
    },
}


MARKETPLACE_ALIASES = {
    "wordpress": "woocommerce",
    "word_press": "woocommerce",
    "woo_commerce": "woocommerce",
    "mercadolivre": "mercado_livre",
    "ml": "mercado_livre",
    "iqfome": "aiqfome",
    "aiq_fome": "aiqfome",
    "magazine_luiza": "magalu",
    "magazine_luiza_magalu": "magalu",
    "facebook": "facebook_marketplace",
    "facebook_marktplace": "facebook_marketplace",
    "whatsapp_marketplace": "whatsapp",
}


def normalize_marketplace_provider(value):
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return MARKETPLACE_ALIASES.get(normalized, normalized)


def marketplace_channel(value):
    provider = normalize_marketplace_provider(value)
    return provider, MARKETPLACE_CHANNELS.get(provider)


def marketplace_catalog():
    return [
        {"provider": provider, **channel}
        for provider, channel in MARKETPLACE_CHANNELS.items()
    ]


def validate_credential_env_prefix(value):
    prefix = str(value or "").strip().upper()
    if not prefix or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", prefix):
        raise ValueError("Informe um prefixo de ambiente valido, como NANOSTORE_ML_LOJA1.")
    return prefix
