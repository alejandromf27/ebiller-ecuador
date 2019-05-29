# -*- coding: utf-8 -*-

import base64
import StringIO
import re, os
from openerp.tools import config

from datetime import datetime

from openerp import models, fields, api
from openerp.exceptions import Warning
from openerp.addons.ec_einvoice import utils
from ..xades.sri import SriService
try:
    from suds.client import Client
except ImportError:
    raise ImportError('Instalar Libreria suds: pip install suds-jurko')

import logging

_logger = logging.getLogger(__name__)


class Edocument(models.AbstractModel):

    _name = 'account.edocument'
    _FIELDS = {
        'account.invoice': 'num_retention',
        'account.invoice.retention': 'num_comprobante'
    }
    SriServiceObj = SriService()

    clave_acceso = fields.Char(
        'Clave de Acceso',
        size=49,
        readonly=True
    )
    numero_autorizacion = fields.Char(
        'Número de Autorización',
        size=49,
        readonly=True
    )
    estado_autorizacion = fields.Char(
        'Estado de Autorización',
        size=64,
        readonly=True
    )
    fecha_autorizacion = fields.Datetime(
        'Fecha Autorización',
        readonly=True
    )
    ambiente = fields.Char(
        'Ambiente',
        size=64,
        readonly=True
    )
    autorizado_sri = fields.Boolean('¿Autorizado SRI?', readonly=True)
    security_code = fields.Char('Código de Seguridad', size=8)
    emission_code = fields.Char('Tipo de Emisión', size=1)

    def get_auth(self, document):
        if document._name == 'account.invoice':
            return document.journal_id.auth_id
        elif document._name == 'account.retention':
            return document.invoice_id.journal_id.auth_ret_id

    def get_secuencial(self):
        return getattr(self, self._FIELDS[self._name])

    def _info_tributaria(self, document, access_key, emission_code):
        """
        """
        ptoemision = document.autorization.code if hasattr(document, 'autorization') else document.emision_point_id.code
        company = document.company_id
        #auth = self.get_auth(document)
        infoTributaria = {
            'ambiente': self.env.user.company_id.env_service,
            'tipoEmision': emission_code,
            'razonSocial': company.name,
            'nombreComercial': company.name,
            'ruc': company.partner_id.vat,
            'claveAcceso':  access_key,
            'codDoc': utils.tipoDocumento['01'],
            'estab': document.company_id.establishment_code,
            'ptoEmi': ptoemision,
            'secuencial': self.get_secuencial(),
            'dirMatriz': company.street
        }
        return infoTributaria

    def get_code(self):
        code = self.env.ref('ec_einvoice.sequence_edocuments_code_sequence')
        return code._next()

    def get_access_key(self, name):
        if name == 'account.invoice':
            #auth = self.journal_id.auth_id
            ld = self.date_invoice.split('-')
            field = 'num_retention'
            numero = getattr(self, field)
            tcomp = utils.tipoDocumento['01']
            serie = '{0}{1}'.format(self.company_id.establishment_code, self.emision_point_id.code)
        elif name == 'account.retention':
            #auth = self.invoice_id.journal_id.auth_ret_id
            ld = self.fecha.split('-')
            field = 'name'
            numero = getattr(self, field)
            tcomp = utils.tipoDocumento['07']
            serie = '{0}{1}'.format(self.company_id.establishment_code, self.autorization.code)
        ld.reverse()
        fecha = ''.join(ld)
        ruc = self.company_id.partner_id.vat


        codigo_numero = self.get_code()
        tipo_emision = self.company_id.emission_code
        access_key = (
            [fecha, tcomp, ruc],
            [serie, numero, codigo_numero, tipo_emision]
            )
        print(access_key)
        return access_key

    @api.multi
    def _get_codes(self, name='account.invoice'):
        ak_temp = self.get_access_key(name)
        self.SriServiceObj.set_active_env(self.env.user.company_id.env_service)
        access_key = self.SriServiceObj.create_access_key(ak_temp)
        emission_code = self.company_id.emission_code
        return access_key, emission_code

    @api.multi
    def check_before_sent(self):
        """
        """
        NOT_SENT = u'No se puede enviar el comprobante electrónico al SRI'
        MESSAGE_SEQUENCIAL = ' '.join([
            u'Los comprobantes electrónicos deberán ser',
            u'enviados al SRI para su autorización en orden cronológico',
            'y secuencial. Por favor enviar primero el',
            ' comprobante inmediatamente anterior.'])
        FIELD = {
            'account.invoice': 'supplier_invoice_number',
            'account.invoice.retention': 'num_comprobante'
        }
        number = getattr(self, FIELD[self._name])
        sql = ' '.join([
            "SELECT autorizado_sri, %s FROM %s" % (FIELD[self._name], self._table),  # noqa
            "WHERE state='open' AND %s < '%s'" % (FIELD[self._name], number),  # noqa
            self._name == 'account.invoice' and "AND type = 'out_invoice'" or '',
            "ORDER BY %s DESC LIMIT 1" % FIELD[self._name]
        ])
        self.env.cr.execute(sql)
        res = self.env.cr.fetchone()
        if not res:
            return True
        auth, number = res
        if auth is None and number:
            raise Warning(NOT_SENT, MESSAGE_SEQUENCIAL)
        return True

    def echeck_date(self, date_invoice):
        """
        Validar que el envío del comprobante electrónico
        se realice dentro de las 24 horas posteriores a su emisión
        """
        LIMIT_TO_SEND = 5
        NOT_SENT = u'Error de Envío'
        MESSAGE_TIME_LIMIT = u' '.join([
            u'Los comprobantes electrónicos deben',
            u'enviarse con máximo 24h desde su emisión.']
        )
        dt = datetime.strptime(date_invoice, '%Y-%m-%d')
        days = (datetime.now() - dt).days
        if days > LIMIT_TO_SEND:
            raise Warning(NOT_SENT, MESSAGE_TIME_LIMIT)

    @api.multi
    def update_document(self, auth, codes):
        DATE_SRI = "%Y-%m-%d %H:%M:%S"
        if auth:
            self.write({
                'numero_autorizacion': auth.numeroAutorizacion if auth else '',
                'estado_autorizacion': auth.estado if auth else '',
                'ambiente': auth.ambiente if auth else '',
                'fecha_autorizacion': auth.fechaAutorizacion.strftime(DATE_SRI) if auth else '',
                'autorizado_sri': True,
            })
            if self.type == 'out_invoice':
                auth_einvoice = self.render_authorized_einvoice(auth)
                attach_xml_id = self.add_attachment(auth_einvoice, auth)
                self.send_einvoice(self, attach_xml_id)
            else:
                auth_document = self.render_authorized_document(auth)
                attach_xml_id = self.add_attachment(auth_document, auth)
                self.send_eretention(self, attach_xml_id)
        else:
            self.write({
                'clave_acceso': codes[0],
                'emission_code': codes[1]
            })

    @api.one
    def add_attachment(self, xml_element, auth):
        buf = StringIO.StringIO()
        buf.write(xml_element.encode('utf-8'))
        document = base64.encodestring(buf.getvalue())
        buf.close()
        attach = self.env['ir.attachment'].create(  # noqa
            {
                'name': '{0}.xml'.format(self.clave_acceso),
                'datas': document,
                'datas_fname':  '{0}.xml'.format(self.clave_acceso),
                'res_model': self._name,
                'res_id': self.id,
                'type': 'binary'
            },
        )
        return attach.id

    def render_document(self, document, access_key, emission_code):
        pass

    def request_authorization(self, access_key):
        messages = []
        SriService.set_active_env(self.env.user.company_id.env_service)
        client = Client(SriService.get_active_ws()[1])
        result = client.service.autorizacionComprobante(access_key)
        autorizacion = result.autorizaciones[0][0]
        mensajes = autorizacion.mensajes and autorizacion.mensajes[0] or []
        #print('Estado de autorizacion %s' % autorizacion.estado)
        for m in mensajes:
            messages.append([m.identificador, m.mensaje])
        if not autorizacion.estado == 'AUTORIZADO':
            return False, messages
        return autorizacion, messages

    @api.model
    def _filestore(self):
        return config.filestore(self._cr.dbname)

    @api.model
    def _full_path(self, path):
        path = re.sub('[.]', '.', path)
        path = path.strip('/\\')
        return os.path.join(self._filestore(), path)