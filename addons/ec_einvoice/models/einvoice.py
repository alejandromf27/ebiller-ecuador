# -*- coding: utf-8 -*-
from openerp import models, api
import logging, time
import itertools
import os
from jinja2 import Environment, FileSystemLoader

#####FE SRI ECUADOR
from openerp.addons.ec_einvoice import utils
from ..xades.sri import DocumentXML
from ..xades.xades import Xades


##### FIN FE SRI ECUADOR


class account_invoice(models.Model):
    _name = 'account.invoice'
    _inherit = ['account.invoice', 'account.edocument']
    _logger = logging.getLogger('account.edocument')

    ######## FE SRI ECUADOR
    def _info_factura(self, invoice):
        """
        """
        company = invoice.company_id
        partner = invoice.partner_id
        infoFactura = {
            'fechaEmision': time.strftime('%d/%m/%Y',
                                          time.strptime(invoice.date_invoice,
                                                        '%Y-%m-%d')),
            'dirEstablecimiento': company.street2,
            'obligadoContabilidad': 'SI',
            'tipoIdentificacionComprador': utils.tipoIdentificacion[partner.identification_type],  # noqa
            'razonSocialComprador': partner.name,
            'identificacionComprador': partner.vat,
            'totalSinImpuestos': '%.2f' % (invoice.amount_untaxed),
            'totalDescuento': '0.00',
            'propina': '0.00',
            'importeTotal': '{:.2f}'.format(invoice.amount_total),
            'moneda': 'DOLAR'
        }
        #if company.partner_id.property_account_position and company.partner_id.property_account_position.name == 'CONTRIBUYENTE ESPECIAL':
        infoFactura.update({'contribuyenteEspecial': '000'})

        totalConImpuestos = []
        for inv_tax in invoice.tax_line:
            if inv_tax.ec_group_tax_use in ['vat', 'vat0', 'ice', 'other']:
                totalImpuesto = {
                    'codigo': utils.tabla17[inv_tax.ec_group_tax_use],
                    'codigoPorcentaje': utils.tabla18[str(inv_tax.percent)],
                    'baseImponible': '{:.2f}'.format(inv_tax.base_amount),
                    'tarifa': inv_tax.percent*100,
                    'valor': '{:.2f}'.format(inv_tax.tax_amount)
                    }
                totalConImpuestos.append(totalImpuesto)

        infoFactura.update({'totalConImpuestos': totalConImpuestos})

        formapagos = []
        for pay in invoice.payment_method_ids:
            pago = {
                    'formaPago': '20',
                    'total': '{:.2f}'.format(invoice.amount_total),
                    'plazo': 0,
                    'unidadTiempo': 'dias'
                }
            formapagos.append(pago)

        infoFactura.update({'pagos': formapagos})

        return infoFactura

    def _detalles(self, invoice):
        """
        """
        def fix_chars(code):
            special = [
                [u'%', ' '],
                [u'º', ' '],
                [u'Ñ', 'N'],
                [u'ñ', 'n']
            ]
            for f, r in special:
                code = code.replace(f, r)
            return code

        detalles = []
        for line in invoice.invoice_line:
            codigoPrincipal = line.product_id and \
                line.product_id.default_code and \
                fix_chars(line.product_id.default_code) or '001'
            detalle = {
                'codigoPrincipal': codigoPrincipal,
                'descripcion': fix_chars(line.name.strip()),
                'cantidad': '%.6f' % (line.quantity),
                'precioUnitario': '%.6f' % (line.price_unit),
                'descuento': '0.00',
                'precioTotalSinImpuesto': '%.2f' % (line.price_subtotal)
            }
            impuestos = []
            for tax_line in line.invoice_line_tax_id:
                if tax_line.ec_group_tax_use in ['vat', 'vat0', 'ice']:
                    impuesto = {
                        'codigo': utils.tabla17[tax_line.ec_group_tax_use],
                        'codigoPorcentaje': utils.tabla18[str(tax_line.amount)],  # noqa
                        'tarifa': tax_line.amount*100,
                        'baseImponible': '{:.2f}'.format(line.price_subtotal),
                        'valor': '{:.2f}'.format(line.price_subtotal *
                                                 tax_line.amount)
                    }
                    impuestos.append(impuesto)
            detalle.update({'impuestos': impuestos})
            detalles.append(detalle)
        return {'detalles': detalles}

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
    def action_generate_einvoice(self):
        """
        Metodo de generacion de factura electronica
        TODO: usar celery para enviar a cola de tareas
        la generacion de la factura y envio de email`
        """
        for obj in self:
            if obj.type not in ['out_invoice', 'out_refund']:
                continue

            self.echeck_date(obj.date_invoice)
            self.check_before_sent()
            access_key, emission_code = self._get_codes(name='account.invoice')  # noqa
            if obj.type == 'out_invoice':
                einvoice = self.render_document(obj, access_key, emission_code)
                inv_xml = DocumentXML(einvoice, 'out_invoice')
                inv_xml.validate_xml()
                xades = Xades()
                file_pk12 = obj.company_id.electronic_file._full_path(obj.company_id.electronic_file.store_fname)
                self._logger.info('LLAVE DIGITAL')
                self._logger.info(file_pk12)
                password = obj.company_id.password_electronic_signature
                signed_document = xades.sign(obj, einvoice, file_pk12, password)
                ok, errores = inv_xml.send_receipt(signed_document)
                if ok:
                    obj.sent_to_center = True
                else:
                    raise Warning('Errores', errores)

                obj.update_document(False, [access_key, emission_code])

            else:
                # Revisar codigo que corre aca
                if not obj.origin:
                    raise Warning('Error de Datos',
                                  u'Sin motivo de la devolución')
                inv_ids = self.search([('number', '=', obj.name)])
                factura_origen = self.browse(inv_ids)
                # XML del comprobante electrónico: factura
                factura = self._generate_xml_refund(obj, factura_origen, access_key, emission_code)  # noqa
                # envío del correo electrónico de nota de crédito al cliente
                self.send_mail_refund(obj, access_key)


    def send_einvoice(self, obj, attach_xml_id):
        self._logger.info('Enviando documento electronico por correo')
        template = self.env.ref('ec_einvoice.email_template_einvoice')
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
            obj.company_id.establishment_code + obj.emision_point_id.code + obj.num_retention,
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

    def render_document(self, invoice, access_key, emission_code):
        tmpl_path = os.path.join(os.path.dirname(__file__), '../templates')
        env = Environment(loader=FileSystemLoader(tmpl_path))
        einvoice_tmpl = env.get_template('einvoice.xml')
        data = {}
        data.update(self._info_tributaria(invoice, access_key, emission_code))
        data.update(self._info_factura(invoice))
        data.update(self._detalles(invoice))
        einvoice = einvoice_tmpl.render(data)
        return einvoice

    def render_authorized_einvoice(self, autorizacion):
        tmpl_path = os.path.join(os.path.dirname(__file__), '../templates')
        env = Environment(loader=FileSystemLoader(tmpl_path))
        einvoice_tmpl = env.get_template('authorized_einvoice.xml')
        auth_xml = {
            'estado': autorizacion.estado,
            'numeroAutorizacion': autorizacion.numeroAutorizacion,
            'ambiente': autorizacion.ambiente,
            'fechaAutorizacion': str(autorizacion.fechaAutorizacion.strftime("%d/%m/%Y %H:%M:%S")),  # noqa
            'comprobante': autorizacion.comprobante
        }
        auth_invoice = einvoice_tmpl.render(auth_xml)
        return auth_invoice





    ####### FIN FE SRI ECUADOR