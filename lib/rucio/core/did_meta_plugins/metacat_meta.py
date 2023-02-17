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

from typing import TYPE_CHECKING

from metacat.webapi import MetaCatClient

from rucio.common.types import InternalScope
from rucio.core.did_meta_plugins.did_meta_plugin_interface import DidMetaPlugin

class MetaCatRucioPlugin(DidMetaPlugin):    
    def __init__(self, client):
        super(MetaCatRucioPlugin, self).__init__()
        # FIXME: initialise this properly
        self.Client = client
        self.plugin_name = "METACAT"
        
    def get_metadata(self, scope, name, *, session: "Optional[Session]" = None):
        info = self.Cient.get_file_info(name=f"{scope}:{name}")
        return info.Metadata

    def set_metadata(self, scope, name, key, value, recursive=False, *,
                     session: "Optional[Session]" = None):
        self.Client.update_file_meta(
            {key:value},
            names=[f"{scope}:{name}"]
        )

    def set_metadata_bulk(self, scope, name, meta, recursive=False, *,
                          session: "Optional[Session]" = None):
        self.Client.update_file_meta(
            meta,
            names=[f"{scope}:{name}"]
        )

    def delete_metadata(self, scope, name, key, *,
                        session: "Optional[Session]" = None):
        meta = self.get_metadata(scope, name)
        try:    del meta[key]
        except KeyError:    return
        self.Client.update_file_meta(
            meta,
            names=[f"{scope}:{name}"],
            mode="replace"
        )

    def list_dids(self, scope, filters, did_type='collection', ignore_case=False,
                  limit=None, offset=None, long=False, recursive=False,
                  ignore_dids=None, *, session: "Optional[Session]" = None):
        # FIXME: implement offset
        # FIXME: implement ignore_case
        if not ignore_dids:
            ignore_dids = set()
        where_items = []
        for k, v in filters.items():
            if isinstance(v, str):
                where_items.append(f"{k} = '{v}'")
            else:
                where_items.append(f"{k} = {v}")
        where_clause = " and ".join(where_items)
                  
        if did_type in ("collection", "dataset", "container"):
            if where_clause:    where_clause = " having "+where_clause
            query = f"datasets {scope}:'%' {where_clause}"
            if recursive:
                query += " with children recursively"
        else:
            if where_clause:    where_clause = " where "+where_clause
            query = f"files from {scope}:'%'"
            if recursive:
                query += " with children recursively"
            query += where_clause
        
        if limit is not None:
            query += f" limit {limit}"
            
        results = self.Client.run_query(query)
        for item in results:
            did_full = scope + ":" + item['name']
            if did_full not in ignore_dids:
                if long:
                    # FIXME: see if we actually can return some of this stuff
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

