# -*- encoding: utf-8 -*-
from openerp import models, api, fields
from ..xades.sri import DocumentXML
from ..xades.xades import Xades
import itertools
import os
import logging
from jinja2 import Environment, FileSystemLoader
import time
from openerp.addons.ec_einvoice import utils


class account_invoice_retention(models.Model):
    _name = 'account.invoice.retention'
    _inherit = ['account.invoice.retention', 'account.edocument']
    _logger = logging.getLogger('account.edocument')

    sent_to_center = fields.Boolean()

    @api.multi
    def auth_doc_sri(self):
        for obj in self:
            auth, m = obj.request_authorization(obj.clave_acceso)
            if auth:
                obj.update_document(auth, [obj.clave_acceso, obj.emission_code])
            else:
                msg = ' '.join(list(itertools.chain(*m)))
                raise Warning('Error', msg)

    @api.multi
    def action_generate_document(self):
        """
        """
        for obj in self:
            #self.echeck_date(obj.fecha)
            self.check_before_sent()
            access_key, emission_code = self._get_codes('account.retention')
            ewithdrawing = self.render_document(obj, access_key, emission_code)
            inv_xml = DocumentXML(ewithdrawing, 'withdrawing')
            inv_xml.validate_xml()
            xades = Xades()
            file_pk12 = obj.company_id.electronic_file._full_path(obj.company_id.electronic_file.store_fname)
            password = obj.company_id.password_electronic_signature
            signed_document = xades.sign(obj, ewithdrawing, file_pk12, password)
            ok, errores = inv_xml.send_receipt(signed_document)
            if ok:
                obj.sent_to_center = True
            else:
                raise Warning('Errores', errores)
            auth, m = inv_xml.request_authorization(access_key)
            if ok:
                obj.sent_to_center = True
            else:
                msg = ' '.join(list(itertools.chain(*m)))
                raise Warning('Error', msg)
            obj.update_document(False, [access_key, emission_code])
            return True

    def render_document(self, document, access_key, emission_code):
        tmpl_path = os.path.join(os.path.dirname(__file__), '../templates')
        env = Environment(loader=FileSystemLoader(tmpl_path))
        ewithdrawing_tmpl = env.get_template('ewithdrawing.xml')
        data = {}
        data.update(self._info_tributaria_ret(document, access_key, emission_code))
        data.update(self._info_withdrawing(document))
        data.update(self._impuestos(document))
        edocument = ewithdrawing_tmpl.render(data)
        #self._logger.debug(edocument)
        return edocument

    def _info_withdrawing(self, withdrawing):
        """
        """
        # generar infoTributaria
        company = withdrawing.company_id
        partner = withdrawing.invoice_id.partner_id
        infoCompRetencion = {
            'fechaEmision': time.strftime('%d/%m/%Y',
                                          time.strptime(withdrawing.fecha,
                                                        '%Y-%m-%d')),
            'dirEstablecimiento': company.street,
            'obligadoContabilidad': 'SI',
            'tipoIdentificacionSujetoRetenido': utils.tipoIdentificacion[partner.identification_type],  # noqa
            'razonSocialSujetoRetenido': partner.name,
            'identificacionSujetoRetenido': partner.vat,
            'periodoFiscal': time.strftime('%m/%Y', time.strptime(withdrawing.fecha, '%Y-%m-%d')),
            }
        #if company.company_registry:
        infoCompRetencion.update({'contribuyenteEspecial': '000'})  # noqa
        return infoCompRetencion

    def render_authorized_document(self, autorizacion):
        tmpl_path = os.path.join(os.path.dirname(__file__), '../templates')
        env = Environment(loader=FileSystemLoader(tmpl_path))
        edocument_tmpl = env.get_template('authorized_withdrawing.xml')
        auth_xml = {
            'estado': autorizacion.estado,
            'numeroAutorizacion': autorizacion.numeroAutorizacion,
            'ambiente': autorizacion.ambiente,
            'fechaAutorizacion': str(autorizacion.fechaAutorizacion.strftime("%d/%m/%Y %H:%M:%S")),  # noqa
            'comprobante': autorizacion.comprobante
        }
        auth_withdrawing = edocument_tmpl.render(auth_xml)
        return auth_withdrawing

    def _impuestos(self, retention):
        """
        """
        def get_codigo_retencion(linea):
            if linea.ec_group_tax_use in ['ret_ir', 'ret_vat']:
                if linea.percent == '30':
                    return '1'
                elif line.percent == '70':
                    return '2'
                else:
                    return '3'
            else:
                return linea.base_code_id.code

        impuestos = []
        for line in retention.tax_line:
            impuesto = {
                'codigo': utils.tabla20[line.ec_group_tax_use],
                'codigoRetencion': line.tax_code_id.fe_rate_code,
                'baseImponible': '%.2f' % (line.base),
                'porcentajeRetener': str(int(abs(line.percent*100))),
                'valorRetenido': '%.2f' % (abs(line.amount)),
                'codDocSustento': '01',
                'numDocSustento': '%s%s%s'%(retention.invoice_id.auth_inv_id.serie_entidad, retention.invoice_id.auth_inv_id.serie_emision, str(retention.invoice_id.supplier_invoice_number).zfill(9),),
                'fechaEmisionDocSustento': time.strftime('%d/%m/%Y', time.strptime(retention.invoice_id.date_invoice, '%Y-%m-%d'))  # noqa
            }
            impuestos.append(impuesto)
        return {'impuestos': impuestos}

    def _info_tributaria_ret(self, document, access_key, emission_code):
        """
        """
        company = document.company_id
        #auth = self.get_auth(document)
        infoTributaria = {
            'ambiente': self.env.user.company_id.env_service,
            'tipoEmision': emission_code,
            'razonSocial': company.name,
            'nombreComercial': company.name,
            'ruc': company.partner_id.vat,
            'claveAcceso':  access_key,
            'codDoc': utils.tipoDocumento['07'],
            'estab': company.establishment_code,
            'ptoEmi': document.autorization.code,
            'secuencial': document.get_secuencial(),
            'dirMatriz': company.street
        }
        return infoTributaria

    def send_eretention(self, obj, attach_xml_id):
        self._logger.info('Enviando documento electronico por correo')
        template = self.env.ref('ec_einvoice.email_template_retention')
        template.attachment_ids = [(6, 0, attach_xml_id)]

        mail_to = ['droman@pelotea.com']
        if obj.partner_id.email:
            mail_to.append(obj.partner_id.email)
        if self.env.user.partner_id.email:
            mail_to.append(obj.env.user.partner_id.email)

        template.email_to = ','.join(mail_to)
        #text
        body = u"""
            <p><strong>%s</strong></p>
            <p>R.U.C.: %s</p>
            <p>Teléfono: %s</p>
            <p>Cliente: %s</p>
            <p>R.U.C.: %s</p>
            <p>Email: %s</p>
            <p><strong>DATOS DEL DOCUMENTO</strong></p>
            <p>Documento: %s</p>
            <p>Clave de acceso: %s</p>
            <p>Número de autorización: %s</p>
            <p>Ambiente: %s</p>
            <p>Emisión: %s</p>
            <p>Fecha y hora Autorización: %s</p>
        """ % (
            obj.company_id.name,
            obj.company_id.vat,
            obj.company_id.phone,
            obj.partner_id.name,
            obj.partner_id.vat,
            obj.partner_id.email,
            obj.company_id.establishment_code + obj.autorization.code + obj.num_comprobante,
            obj.clave_acceso,
            obj.numero_autorizacion,
            obj.ambiente,
            'Normal' if obj.company_id.emission_code == '1' else 'Indisponibilidad',
            obj.fecha_autorizacion
        )
        template.body_html = body
        template.send_mail(obj.id)
        obj.sent = True
        return True
