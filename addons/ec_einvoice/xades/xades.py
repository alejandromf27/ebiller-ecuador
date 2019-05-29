# -*- coding: utf-8 -*-

import base64
import os
import subprocess
import logging
from openerp.tools import ustr
from openerp.http import serialize_exception
from openerp.exceptions import ValidationError
from openerp.tools.translate import _

_logger = logging.getLogger(__name__)


class CheckDigit(object):

    # Definicion modulo 11
    _MODULO_11 = {
        'BASE': 11,
        'FACTOR': 2,
        'RETORNO11': 0,
        'RETORNO10': 1,
        'PESO': 2,
        'MAX_WEIGHT': 7
    }

    @classmethod
    def _eval_mod11(self, modulo):
        if modulo == self._MODULO_11['BASE']:
            return self._MODULO_11['RETORNO11']
        elif modulo == self._MODULO_11['BASE'] - 1:
            return self._MODULO_11['RETORNO10']
        else:
            return modulo

    @classmethod
    def compute_mod11(self, dato):
        """
        Calculo mod 11
        return int
        """
        total = 0
        weight = self._MODULO_11['PESO']

        for item in reversed(dato):
            total += int(item) * weight
            weight += 1
            if weight > self._MODULO_11['MAX_WEIGHT']:
                weight = self._MODULO_11['PESO']
        mod = 11 - total % self._MODULO_11['BASE']

        mod = self._eval_mod11(mod)
        return mod


class Xades(object):

    def sign1(self, xml_document, file_pk12, password):
        """
        Metodo que aplica la firma digital al XML
        TODO: Revisar return
        """
        xml_str = xml_document.encode('utf-8')
        JAR_PATH = 'firma/firmaXadesBes.jar'
        JAVA_CMD = 'java'
        firma_path = os.path.join(os.path.dirname(__file__), JAR_PATH)
        command = [
            JAVA_CMD,
            '-jar',
            firma_path,
            xml_str,
            base64.b64encode(file_pk12),
            password

        ]
        try:
            subprocess.check_output(command)
        except subprocess.CalledProcessError as e:
            raise e.returncode

        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        res = p.communicate()
        assert False
        return res[0]


    def sign(self, doc_obj, xml_document, file_pk12, password):
        xml_str = xml_document.encode('utf-8')
        #create xml unsigned
        fname_xml = str(doc_obj.create_uid.id) + '_' + str(doc_obj.id) + '_byuser_unsigned.xml'
        full_path_xml = doc_obj._full_path(fname_xml)
        file_xml = open(full_path_xml, 'w+')
        file_xml.write(xml_str)
        file_xml.close()
        jar_path = os.path.join(os.path.dirname(__file__), 'firma/signFile.jar')
        try:
            process = subprocess.Popen(['java',
                             '-Dfile.encoding=UTF8',
                             '-jar',
                             jar_path,
                             xml_str,
                             file_pk12,
                             password],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
            signed_xml = process.communicate()[0]

        except (Exception,) as e:
            raise ValidationError(_("A ocurrido un error firmando el xml, verifique la configuracion del emisor: %s" % str(e)))
        if not signed_xml:
            raise ValidationError(_("A ocurrido un error firmando el xml, verifique la configuracion del emisor"))
        else:
            # xml signed
            fname_signed_xml = str(doc_obj.create_uid.id) + '_' + str(doc_obj.id) + '_byuser_signed.xml'
            full_path_signed_xml = doc_obj._full_path(fname_signed_xml)
            file_signed_xml = open(full_path_signed_xml, 'w+')
            file_signed_xml.write(signed_xml)
            file_signed_xml.close()
        _logger.error("ARCHIVO XML FIRMADO " + ustr(signed_xml))

        return signed_xml


