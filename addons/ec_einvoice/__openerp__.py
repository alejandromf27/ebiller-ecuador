# -*- coding: utf-8 -*-
##############################################################################
#
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
{
    'name': 'FE SRI Ecuador',
    'version': '1.1',
    'category': 'Account Billing',
    'description': """
    """,
    'author': 'Angel Garcia(alejandromf27@gmail.com)',
    'depends': [],
    'data': [
        ''
        'edi/einvoice_edi.xml',
        'edi/eretention_edi.xml',
        'data/data_einvoice.xml',
        'views/company_views.xml',
        'views/einvoice_views.xml',
        'views/retention.xml',
    ],
    'installable': True,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
