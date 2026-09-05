{
    'name': 'Contratos de suministro',
    'summary': 'Contratos por institución y razón social: claves, cantidades, precios, monto; avance por monto y por clave; alertas de saldo',
    'version': '19.0.2.0.0',
    'category': 'Distribución de insumos',
    'author': 'Alphaqueb Consulting SAS',
    'license': 'LGPL-3',
    'icon': '/biotex_contract/static/description/icon.svg',
    'depends': ['biotex_base', 'biotex_catalog', 'sale_management', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'security/contract_security.xml',
        'data/contract_data.xml',
        'views/biotex_contract_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': ['biotex_contract/static/src/**/*'],
    },
    'installable': True,
}
