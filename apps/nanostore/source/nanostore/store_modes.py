STORE_MODES = {
    "pharmacy": {
        "name": "Farmacia", "short_name": "Farmacia", "entity": "medicamento ou produto",
        "catalog": "Medicamentos e produtos", "sales": "Vendas", "sale": "Venda de balcao",
        "inventory": "Estoque por lote", "purchases": "Compras", "workflow": "Atendimentos",
        "dashboard_title": "Operacao da farmacia", "dashboard_copy": "Validades, estoque, dispensacao, vendas e caixa em uma leitura unica.",
        "primary_action": "Nova venda", "accent": "green", "tracks_inventory": True,
        "show_lots": True, "show_fiscal": True, "show_workflow": True,
    },
    "store": {
        "name": "Loja", "short_name": "Varejo", "entity": "produto",
        "catalog": "Catalogo", "sales": "PDV e pedidos", "sale": "Venda no PDV",
        "inventory": "Estoque", "purchases": "Reposicao", "workflow": "Pedidos",
        "dashboard_title": "Painel da loja", "dashboard_copy": "Vendas, pedidos, estoque e caixa para a rotina do varejo.",
        "primary_action": "Abrir PDV", "accent": "blue", "tracks_inventory": True,
        "show_lots": False, "show_fiscal": True, "show_workflow": True,
    },
    "distributor": {
        "name": "Distribuidora", "short_name": "Distribuicao", "entity": "item",
        "catalog": "Catalogo e embalagens", "sales": "Pedidos de venda", "sale": "Novo pedido",
        "inventory": "Armazem", "purchases": "Recebimentos", "workflow": "Separacao e entrega",
        "dashboard_title": "Central de distribuicao", "dashboard_copy": "Pedidos, recebimentos, separacao, estoque e financeiro por prioridade.",
        "primary_action": "Novo pedido", "accent": "gold", "tracks_inventory": True,
        "show_lots": True, "show_fiscal": True, "show_workflow": True,
    },
    "commerce": {
        "name": "Comercio", "short_name": "Comercio", "entity": "produto",
        "catalog": "Produtos", "sales": "Vendas", "sale": "Registrar venda",
        "inventory": "Estoque", "purchases": "Compras", "workflow": "Negociacoes",
        "dashboard_title": "Gestao comercial", "dashboard_copy": "Vendas, compras, estoque, recebimentos e desempenho comercial.",
        "primary_action": "Nova venda", "accent": "teal", "tracks_inventory": True,
        "show_lots": False, "show_fiscal": True, "show_workflow": True,
    },
    "food": {
        "name": "Alimentos", "short_name": "Alimentos", "entity": "produto",
        "catalog": "Produtos e insumos", "sales": "Vendas e pedidos", "sale": "Novo pedido",
        "inventory": "Validade e estoque", "purchases": "Entradas", "workflow": "Producao e pedidos",
        "dashboard_title": "Operacao de alimentos", "dashboard_copy": "Pedidos, validade, insumos, vendas e caixa com foco no giro diario.",
        "primary_action": "Novo pedido", "accent": "red", "tracks_inventory": True,
        "show_lots": True, "show_fiscal": True, "show_workflow": True,
    },
    "services": {
        "name": "Prestador de servicos", "short_name": "Servicos", "entity": "servico",
        "catalog": "Servicos", "sales": "Ordens e cobrancas", "sale": "Nova ordem de servico",
        "inventory": "Recursos", "purchases": "Despesas", "workflow": "Agenda e execucao",
        "dashboard_title": "Central de servicos", "dashboard_copy": "Agenda operacional, ordens, clientes, cobrancas e caixa.",
        "primary_action": "Nova ordem", "accent": "violet", "tracks_inventory": False,
        "show_lots": False, "show_fiscal": False, "show_workflow": True,
    },
}


def resolve_store_mode(value):
    key = str(value or "pharmacy").strip().lower()
    if key not in STORE_MODES:
        key = "pharmacy"
    return key, STORE_MODES[key]
