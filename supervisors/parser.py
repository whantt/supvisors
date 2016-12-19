#!/usr/bin/python
#-*- coding: utf-8 -*-

# ======================================================================
# Copyright 2016 Julien LE CLEACH
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ======================================================================

from collections import OrderedDict
from StringIO import StringIO
from sys import stderr

from supervisor.datatypes import boolean, list_of_strings

from supervisors.utils import supervisors_short_cuts


# XSD contents for XML validation
XSDContents = StringIO('''\
<xs:schema attributeFormDefault="unqualified" elementFormDefault="qualified" xmlns:xs="http://www.w3.org/2001/XMLSchema">
    <xs:simpleType name="Loading">
        <xs:restriction base="xs:int">
            <xs:minInclusive value="0"/>
            <xs:maxInclusive value="100"/>
        </xs:restriction>
    </xs:simpleType>
    <xs:complexType name="ProgramModel">
        <xs:choice>
            <xs:element type="xs:string" name="reference"/>
            <xs:sequence>
                <xs:element type="xs:string" name="addresses" minOccurs="0" maxOccurs="1"/>
                <xs:element type="xs:byte" name="start_sequence" minOccurs="0" maxOccurs="1"/>
                <xs:element type="xs:byte" name="stop_sequence" minOccurs="0" maxOccurs="1"/>
                <xs:element type="xs:boolean" name="required" minOccurs="0" maxOccurs="1"/>
                <xs:element type="xs:boolean" name="wait_exit" minOccurs="0" maxOccurs="1"/>
                <xs:element type="Loading" name="expected_loading" minOccurs="0" maxOccurs="1"/>
            </xs:sequence>
        </xs:choice>
        <xs:attribute type="xs:string" name="name" use="required"/>
    </xs:complexType>
    <xs:complexType name="ApplicationModel">
        <xs:sequence>
            <xs:element type="xs:byte" name="start_sequence" minOccurs="0" maxOccurs="1"/>
            <xs:element type="xs:byte" name="stop_sequence" minOccurs="0" maxOccurs="1"/>
            <xs:choice minOccurs="0" maxOccurs="unbounded">
                <xs:element type="ProgramModel" name="program"/>
                <xs:element type="ProgramModel" name="pattern"/>
            </xs:choice>
        </xs:sequence>
        <xs:attribute type="xs:string" name="name" use="required"/>
    </xs:complexType>
    <xs:element name="root">
        <xs:complexType>
            <xs:sequence>
                <xs:choice minOccurs="0" maxOccurs="unbounded">
                    <xs:element type="ProgramModel" name="model"/>
                    <xs:element type="ApplicationModel" name="application"/>
                </xs:choice>
            </xs:sequence>
        </xs:complexType>
    </xs:element>
</xs:schema>
''')

class Parser(object):

    def __init__(self, supervisors):
        self.supervisors = supervisors
        supervisors_short_cuts(self, ['logger'])
        self.tree = self.parse(supervisors.options.deployment_file)
        self.root = self.tree.getroot()
        # get models
        elements = self.root.findall("./model[@name]")
        self.models = {element.get('name'): element for element in elements}
        self.logger.debug(self.models)
        # get patterns
        elements = self.root.findall(".//pattern[@name]")
        self.patterns = {element.get('name'): element for element in elements}
        self.logger.debug(self.patterns)

    def load_application_rules(self, application):
        # find application element
        self.logger.trace('searching application element for {}'.format(application.application_name))
        application_elt = self.root.find("./application[@name='{}']".format(application.application_name))
        if application_elt is not None:
            # get start_sequence rule
            value = application_elt.findtext('start_sequence')
            application.rules.start_sequence = int(value) if value and int(value)>0 else 0
            # get stop_sequence rule
            value = application_elt.findtext('stop_sequence')
            application.rules.stop_sequence = int(value) if value and int(value)>0 else 0
            # final print
            self.logger.debug('application {} - rules {}'.format(application.application_name, application.rules))

    def load_process_rules(self, process):
        self.logger.trace('searching program element for {}'.format(process.namespec()))
        program_elt = self.get_program_element(process)
        if program_elt is not None:
            # get addresses rule
            self.get_program_addresses(program_elt, process.rules)
            # get start_sequence rule
            value = program_elt.findtext('start_sequence')
            process.rules.start_sequence = int(value) if value and int(value)>0 else 0
            # get stop_sequence rule
            value = program_elt.findtext('stop_sequence')
            process.rules.stop_sequence = int(value) if value and int(value)>0 else 0
            # get required rule
            value = program_elt.findtext('required')
            process.rules.required = boolean(value) if value else False
            # get wait_exit rule
            value = program_elt.findtext('wait_exit')
            process.rules.wait_exit = boolean(value) if value else False
            # get expected_loading rule
            value = program_elt.findtext('expected_loading')
            process.rules.expected_loading = int(value) if value and 0 <= int(value) <= 100 else 1
            # check that rules are compliant with dependencies
            process.rules.check_dependencies(process.namespec())
            self.logger.debug('process {} - rules {}'.format(process.namespec(), process.rules))

    def get_program_addresses(self, program_elt, rules):
        value = program_elt.findtext('addresses')
        if value:
            # sort and trim
            addresses = list(OrderedDict.fromkeys(filter(None, list_of_strings(value))))
            rules.addresses = [ '*' ] if '*' in addresses else self.supervisors.address_mapper.filter(addresses)

    def get_program_element(self, process):
        # try to find program name in file
        program_elt = self.root.find("./application[@name='{}']/program[@name='{}']".format(process.application_name, process.process_name))
        self.logger.trace('{} - direct search program element {}'.format(process.namespec(), program_elt))
        if program_elt is None:
            # try to find a corresponding pattern
            patterns = [name for name, element in self.patterns.items() if name in process.namespec()]
            self.supervisors.logger.trace('{} - found patterns {}'.format(process.namespec(), patterns))
            if patterns:
                pattern = max(patterns, key=len)
                program_elt = self.patterns[pattern]
            self.logger.trace('{} - pattern search program element {}'.format(process.namespec(), program_elt))
        if program_elt is not None:
            # find if model referenced in element
            model = program_elt.findtext('reference')
            if model in self.models.keys():
                program_elt = self.models[model]
            self.logger.trace('{} - model search ({}) program element {}'.format(process.namespec(), model, program_elt))
        return program_elt

    def parse(self, filename):
        self.parser = None
        # find parser
        try:
            from lxml.etree import parse, XMLSchema
            self.logger.info('using lxml.etree parser')
            # parse XML and validate it
            tree = parse(filename)
            # get XSD
            schemaDoc = parse(XSDContents)
            schema = XMLSchema(schemaDoc)
            xml_valid = schema.validate(tree)
            if xml_valid:
                self.logger.info('XML validated')
            else:
                self.logger.error('XML NOT validated: {}'.format(filename))
                print >> stderr,  schema.error_log
            return tree if xml_valid else None
        except ImportError:
            try:
                from xml.etree.ElementTree import parse
                self.logger.info('using xml.etree.ElementTree parser')
                return parse(filename)
            except ImportError:
                self.logger.critical("Failed to import ElementTree from any known place")
                raise
