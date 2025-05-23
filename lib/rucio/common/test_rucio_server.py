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

import unittest
from os import remove
from os.path import basename

from rucio.common.utils import execute
from rucio.common.utils import generate_uuid as uuid


def file_generator(size=2048, namelen=10):
    """ Create a bogus file and returns it's name.
    :param size: size in bytes
    :returns: The name of the generated file.
    """
    fn = '/tmp/rucio_testfile_' + uuid()
    execute('dd if=/dev/urandom of={0} count={1} bs=1'.format(fn, size))
    return fn


def get_scope_and_rses():
    """
    Check if xrd containers rses for xrootd are available in the testing environment.

    :return: A tuple (scope, rses) for the rucio client where scope is mock/test and rses is a list or (None, [None]) if no suitable rse exists.
    """
    cmd = "rucio rse list 'test_container_xrd=True'"
    print(cmd)
    exitcode, out, err = execute(cmd)
    print(out, err)
    rses = out.split()
    if len(rses) == 0:
        return None, [None]

    scope = 'test'
    account = 'root'
    cmd = f"rucio scope add {scope} --account {account}"
    _, out, err = execute(cmd)
    print(out, err)
    return scope, rses


def delete_rules(did):
    # get the rules for the file
    print('Deleting rules')
    cmd = "rucio rule list {0} | grep {0} | cut -f1 -d\\ ".format(did)
    print(cmd)
    exitcode, out, err = execute(cmd)
    print(out, err)
    rules = out.split()
    # delete the rules for the file
    for rule in rules:
        cmd = "rucio rule remove {0}".format(rule)
        print(cmd)
        exitcode, out, err = execute(cmd)


class TestRucioServer(unittest.TestCase):

    def setUp(self):
        self.marker = '$ > '
        self.scope, self.rses = get_scope_and_rses()
        self.rse = self.rses[0]
        self.generated_dids = []

    def tearDown(self):
        for did in self.generated_dids:
            delete_rules(did)
        self.generated_dids = []

    def test_ping(self):
        """CLIENT (USER): rucio ping"""
        cmd = 'rucio ping'
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(out, err)
        self.assertEqual(exitcode, 0)

    def test_whoami(self):
        """CLIENT (USER): rucio whoami"""
        cmd = 'rucio whoami'
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(out, err)
        self.assertEqual(exitcode, 0)

    def test_upload_download(self):
        """CLIENT(USER): rucio upload files to dataset/download dataset"""
        if self.rse is None:
            return

        tmp_file1 = file_generator()
        tmp_file2 = file_generator()
        tmp_file3 = file_generator()
        tmp_dsn = 'tests.rucio_client_test_server_' + uuid()

        # Adding files to a new dataset
        cmd = 'rucio upload --rse {0} --scope {1} {2} {3} {4} {1}:{5}'.format(self.rse, self.scope, tmp_file1, tmp_file2, tmp_file3, tmp_dsn)
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(out)
        print(err)
        remove(tmp_file1)
        remove(tmp_file2)
        remove(tmp_file3)
        self.assertEqual(exitcode, 0)

        # List the files
        cmd = 'rucio did content list --did {0}:{1}'.format(self.scope, tmp_dsn)
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(out)
        print(err)
        self.assertEqual(exitcode, 0)

        # List the replicas
        cmd = 'rucio replica list file {0}:{1}'.format(self.scope, tmp_dsn)
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(out)
        print(err)
        self.assertEqual(exitcode, 0)

        # Downloading dataset
        cmd = 'rucio download --dir /tmp/ {0}:{1}'.format(self.scope, tmp_dsn)
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(out)
        print(err)
        # The files should be there
        cmd = 'ls /tmp/{0}/rucio_testfile_*'.format(tmp_dsn)
        print(self.marker + cmd)
        exitcode, out, err = execute(cmd)
        print(err, out)
        self.assertEqual(exitcode, 0)

        # cleaning
        remove('/tmp/{0}/'.format(tmp_dsn) + basename(tmp_file1))
        remove('/tmp/{0}/'.format(tmp_dsn) + basename(tmp_file2))
        remove('/tmp/{0}/'.format(tmp_dsn) + basename(tmp_file3))
        added_dids = ['{0}:{1}'.format(self.scope, did) for did in (basename(tmp_file1), basename(tmp_file2), basename(tmp_file3), tmp_dsn)]
        self.generated_dids += added_dids
