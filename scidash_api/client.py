from __future__ import unicode_literals, print_function
import json
import logging
from platform import platform, system

import itertools
import jsonpickle
import requests
import six
import quantities as pq

import sciunit
from sciunit.base import QuantitiesHandler, UnitQuantitiesHandler
from scidash_api import settings
from scidash_api.mapper import ScidashClientMapper
from scidash_api import exceptions
from scidash_api import helper

logger = logging.getLogger(__name__)


class ScidashClient(object):

    """Base client class for all actions with Scidash API"""

    def __init__(self, config=None, build_info=None, hostname=None):
        """__init__

        :param config:
        :param build_info:
        :param hostname:
        """
        self.token = None

        self.config = settings.CONFIG

        self.data = {}
        self.errors = []

        if build_info is None:
            self.build_info = "{}/{}".format(platform(), system())
        else:
            self.build_info = build_info

        self.hostname = hostname

        self.mapper = ScidashClientMapper()

        if config is not None:
            self.config.update(config)

        self.test_config()

    def test_config(self):
        """
        Check, is config is fine
        :returns: void
        :raises: ScidashClientWrongConfigException
        """
        if self.config.get('base_url')[-1] is '/':
            raise exceptions.ScidashClientWrongConfigException('Remove last '
                                                               'slash '
                                                               'from base_url')

    def get_headers(self):
        """
        Shortcut for gettings headers for uploading
        """
        return {
            'Authorization': 'JWT {}'.format(self.token)
        }

    def login(self, username, password):
        """
        Getting API token from Scidash

        :param username:
        :param password:
        """
        credentials = {
                "username": username,
                "password": password
                }

        auth_url = self.config.get('auth_url')
        base_url = self.config.get('base_url')

        r = requests.post('{}{}'.format(base_url, auth_url), data=credentials)

        try:
            self.token = r.json().get('token')
        except Exception as e:
            raise exceptions.ScidashClientException('Authentication'
                                                    ' Failed: {}'.format(e))

        if self.token is None:
            raise exceptions.ScidashClientException('Authentication Failed: '
                    '{}'.format(r.json()))

        return self
    
    def obj_to_dict(self, obj, unpicklable=True, make_refs=False, string=False):
        # Make sure this SciUnit object is in dict form
        if isinstance(obj, six.string_types):
            # Already a serialized string
            result = json.loads(obj)
        elif isinstance(obj, dict):
            # Already a json'd dict
            result = obj
        else:
            # Convert object to dict
            try:
                result = obj.json(add_props=True, string=False, unpicklable=unpicklable, make_refs=make_refs)
            except AttributeError:
                result = json.loads(jsonpickle.encode(result, unpicklable=unpicklable, make_refs=make_refs))
        return result

    def set_data(self, score_data, related_data=None):
        """
        Sets data for uploading

        :param score_data:
        :returns: self
        """

        score_data = self.obj_to_dict(score_data)
        if related_data is not None:
            related_data = self.obj_to_dict(related_data)
            if 'py/state' in score_data:
                score_data['py/state']['related_data'] = related_data
            else:
                score_data['related_data'] = related_data
           
        self.data  = self.mapper.convert(score_data)

        if self.data is not None:
            self.data.get('test_instance').update({
                "build_info": self.build_info,
                "hostname": self.hostname
                })
        else:
            self.errors = self.errors + self.mapper.errors

        return self

    def upload_test_score(self, data=None, related_data=None):
        """
        Main method for uploading

        :returns: urllib3 requests object
        """

        if data is not None:
            self.set_data(data, related_data)

        if self.data is None:
            return False

        files = {
                'file': (self.config.get('file_name'), json.dumps(self.data))
                }

        headers = self.get_headers()

        upload_url = \
            self.config.get('upload_url') \
            .format(filename=self.config.get('file_name'))
        base_url = self.config.get('base_url')

        r = requests.put('{}{}'.format(base_url, upload_url), headers=headers,
                files=files)

        if r.status_code == 400 or r.status_code == 500:
            self.errors.append(r.text)

            if r.status_code == 400:
                logger.error('SERVER -> INVALID DATA: '
                        '{}'.format(self.errors))

            if r.status_code == 500:
                logger.error('SERVER -> SERVER ERROR: '
                        '{}'.format(self.errors))

        return r

    def upload_score(self, data=None):
        helper.deprecated(method_name="upload_score()",
                will_be_removed="2.0.0", replacement="upload_test_score()")

        return self.upload_test_score(data)

    def upload_suite_score(self, suite, score_matrix):
        """upload_suite

        uploading score matrix with suite information

        :param suite:
        :param score_matrix:

        :returns: urllib3 requests object list
        """
        
        _suite = self.obj_to_dict(suite)
        _score_matrix = self.obj_to_dict(score_matrix)
        
        responses = []
        scores = list(itertools.chain(*score_matrix.scores_flat))
        _scores =list(itertools.chain(*_score_matrix['py/state']['scores_flat']))
        assert len(scores) == len(_scores)
                    
        for score, _score in zip(scores, _scores):
            _test = _get(_score, 'test')
            if not _get(_test, 'test_suites'):
                _set(_test, 'test_suites', [])
            test_suites = _get(_test, 'test_suites')
            test_suites.append(_suite)
            related_data = jsonpickle.encode(score.related_data, make_refs=False, unpicklable=False)
            related_data = json.loads(related_data)
            response = self.upload_test_score(_score, related_data=related_data)
            responses.append(response)

        return responses

    def upload_suite(self, suite, score_matrix):
        helper.deprecated(method_name="upload_suite()",
                will_be_removed="2.0.0", replacement="upload_suite_score()")

        return self.upload_suite_score(suite, score_matrix)

def _get(d, key, default=None):
    if 'py/state' in d:
        return d['py/state'].get(key, default)
    else:
        return d.get(key, default)
    
def _set(d, key, value):
    if 'py/state' in d:
        d['py/state'][key] = value
    else:
        d[key] = value