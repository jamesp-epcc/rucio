# -*- coding: utf-8 -*-
# Copyright European Organization for Nuclear Research (CERN) since 2012
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
from typing import TYPE_CHECKING

from metacat.webapi import MetaCatClient

from rucio.common import config
from rucio.common import exception
from rucio.common.types import InternalScope
from rucio.core.did_meta_plugins.did_meta_plugin_interface import DidMetaPlugin

class MetaCatRucioPlugin(DidMetaPlugin):    
    def __init__(self, client=None):
        super(MetaCatRucioPlugin, self).__init__()
        if client is None:
            metacat_url = config.config_get('metadata', 'metacat_url')
            if metacat_url is None:
                metacat_url = os.environ["METACAT_SERVER_URL"]
            client = MetaCatClient(metacat_url)
            metacat_username = config.config_get('metadata', 'metacat_username', raise_exception=False)
            metacat_password = config.config_get('metadata', 'metacat_password', raise_exception=False)
            if metacat_username is not None and metacat_password is not None:
                client.login_password(metacat_username, metacat_password)
        self.Client = client
        self.plugin_name = "METACAT"
        
    def get_metadata(self, scope, name, *, session: "Optional[Session]" = None):
        info = self.Client.get_file(did=f"{scope}:{name}")
        if info is None:
            return {}
        return info["metadata"]

    def set_metadata(self, scope, name, key, value, recursive=False, *,
                     session: "Optional[Session]" = None):
        self.Client.update_file(
            did=f"{scope}:{name}",
            metadata={key:value}
        )

    def set_metadata_bulk(self, scope, name, meta, recursive=False, *,
                          session: "Optional[Session]" = None):
        self.Client.update_file(
            did=f"{scope}:{name}",
            metadata=meta
        )

    def delete_metadata(self, scope, name, key, *,
                        session: "Optional[Session]" = None):
        meta = self.get_metadata(scope, name)
        try:
            del meta[key]
        except KeyError:
            raise exception.KeyNotFound(key)
        self.Client.update_file(
            metadata=meta,
            did=f"{scope}:{name}",
            replace=True
        )

    # support for case insensitive matching is currently broken in MetaCat
    # so convert string to a regular expression that will do this
    def get_case_insensitive_re(v):
        v = re.escape(v)
        result = ''
        for c in v:
            if c.isalpha():
                result = result + '[' + c.upper() + c.lower() + ']'
            else:
                result = result + c
        return result
        
    def list_dids(self, scope, filters, did_type='collection', ignore_case=False,
                  limit=None, offset=None, long=False, recursive=False,
                  ignore_dids=None, *, session: "Optional[Session]" = None):
        if not ignore_dids:
            ignore_dids = set()
        where_items = []
        for k, v in filters.items():
            if isinstance(v, str):
                if ignore_case:
                    where_items.append(f"{k} ~ '{self.get_case_insensitive_re(v)}'")
                else:
                    where_items.append(f"{k} = '{v}'")
            else:
                where_items.append(f"{k} = {v}")
        where_clause = " and ".join(where_items)
                  
        if did_type in ("collection", "dataset", "container"):
            if where_clause:    where_clause = " having "+where_clause
            query = f"datasets {scope}:* {where_clause}"
            if recursive:
                query += " with subsets recursively"
        else:
            if where_clause:    where_clause = " where namespace='" + scope + "' " + where_clause
            query = f"files"
            if recursive:
                query += " with subsets recursively"
            query += where_clause
        
        if limit is not None:
            query += f" limit {limit}"
        if offset is not None:
            query += f" skip {offset}"
            
        results = self.Client.query(query)
        for item in results:
            did_full = scope + ":" + item['name']
            if did_full not in ignore_dids:
                if long:
                    yield {
                        'scope': InternalScope(scope),
                        'name': item['name'],
                        'did_type': "N/A",
                        'bytes': "N/A",
                        'length': "N/A"
                    }
                else:
                    yield item['name']
                  
    def manages_key(self, key, *, session: "Optional[Session]" = None):
        return True

    def get_plugin_name(self):
        return self.plugin_name

