'''
Copyright (c) 2019 Atos Spain SA. All rights reserved.

This file is part of Croupier.

Croupier is free software: you can redistribute it and/or modify it
under the terms of the Apache License, Version 2.0 (the License) License.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT ANY WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT, IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

See README file for full disclaimer information and LICENSE file for full
license information in the project root.

@author: Javier Carnero
         Atos Research & Innovation, Atos Spain S.A.
         e-mail: javier.carnero@atos.net

slurm_tests.py: Holds the Slurm unit tests
'''


import logging
import unittest

from croupier_plugin.workload_managers.workload_manager import WorkloadManager


class TestSlurm(unittest.TestCase):
    """ Holds slurm tests """

    def __init__(self, methodName='runTest'):
        super(TestSlurm, self).__init__(methodName)
        self.wm = WorkloadManager.factory("SLURM")
        self.logger = logging.getLogger('TestSlurm')

    def test_bad_type_name(self):
        """ Bad name type """
        response = self.wm._build_job_submission_call(42,
                                                      {'command': 'cmd',
                                                       'type': 'SBATCH'},
                                                      self.logger)
        self.assertIn('error', response)

    def test_bad_type_settings(self):
        """ Bad type settings """
        response = self.wm._build_job_submission_call('test',
                                                      'bad type',
                                                      self.logger)
        self.assertIn('error', response)

    def test_bad_settings_command_type(self):
        """ Bad type settings """
        response = self.wm._build_job_submission_call('test',
                                                      'bad type',
                                                      self.logger)
        self.assertIn('error', response)

    def test_empty_settings(self):
        """ Empty job settings """
        response = self.wm._build_job_submission_call('test',
                                                      {},
                                                      self.logger)
        self.assertIn('error', response)

    def test_only_type_settings(self):
        """ Type only as job settings """
        response = self.wm._build_job_submission_call('test',
                                                      {'command': 'cmd',
                                                       'type': 'BAD'},
                                                      self.logger)
        self.assertIn('error', response)

    def test_only_command_settings(self):
        """ Command only as job settings. """
        response = self.wm._build_job_submission_call('test',
                                                      {'command': 'cmd'},
                                                      self.logger)
        self.assertIn('error', response)

    def test_notime_srun_call(self):
        """ srun command without max time set. """
        response = self.wm._build_job_submission_call('test',
                                                      {'command': 'cmd',
                                                       'type': 'SRUN'},
                                                      self.logger)
        self.assertIn('error', response)

    def test_basic_srun_call(self):
        """ Basic srun command. """
        response = self.wm._build_job_submission_call('test',
                                                      {'command': 'cmd',
                                                       'type': 'SRUN',
                                                       'max_time': '00:05:00'},
                                                      self.logger)
        self.assertNotIn('error', response)
        self.assertIn('call', response)

        call = response['call']
        self.assertEqual(call, 'nohup sh -c "srun -J \'test\' ' +
                               '-e test.err -o test.out ' +
                               '-t 00:05:00 cmd; " &')

    def test_complete_srun_call(self):
        """ Complete srun command. """
        response = self.wm._build_job_submission_call('test',
                                                      {'pre': [
                                                          'module load mod1',
                                                          './some_script.sh'],
                                                       'type': 'SRUN',
                                                       'command': 'cmd',
                                                       'stderr_file':
                                                       'stderr.out',
                                                       'stdout_file':
                                                       'stdout.out',
                                                       'partition':
                                                       'thinnodes',
                                                       'nodes': 4,
                                                       'tasks': 96,
                                                       'tasks_per_node': 24,
                                                       'memory': '4GB',
                                                       'qos': 'qos',
                                                       'reservation':
                                                          'croupier',
                                                       'mail_user':
                                                       'user@email.com',
                                                       'mail_type': 'ALL',
                                                       'max_time': '00:05:00',
                                                       'post': [
                                                          './cleanup1.sh',
                                                          './cleanup2.sh']},
                                                      self.logger)
        self.assertNotIn('error', response)
        self.assertIn('call', response)

        call = response['call']
        self.assertEqual(call, 'nohup sh -c "'
                               'module load mod1; ./some_script.sh; '
                               'srun -J \'test\''
                               ' -e stderr.out'
                               ' -o stdout.out'
                               ' -t 00:05:00'
                               ' -p thinnodes'
                               ' -N 4'
                               ' -n 96'
                               ' --ntasks-per-node=24'
                               ' --mem=4GB'
                               ' --reservation=croupier'
                               ' --qos=qos'
                               ' --mail-user=user@email.com'
                               ' --mail-type=ALL'
                               ' cmd; '
                               './cleanup1.sh; ./cleanup2.sh; '
                               '" &')

    def test_basic_sbatch_call(self):
        """ Basic sbatch command. """
        response = self.wm._build_job_submission_call('test',
                                                      {'command': 'cmd',
                                                       'type': 'SBATCH'},
                                                      self.logger)
        self.assertNotIn('error', response)
        self.assertIn('call', response)

        call = response['call']
        self.assertEqual(call, "sbatch --parsable -J 'test' " +
                               "-e test.err -o test.out cmd; ")

    def test_complete_sbatch_call(self):
        """ Complete sbatch command. """
        response = self.wm._build_job_submission_call('test',
                                                      {'pre': [
                                                          'module load mod1',
                                                          './some_script.sh'],
                                                       'type': 'SBATCH',
                                                       'command': 'cmd',
                                                       'stderr_file':
                                                       'stderr.out',
                                                       'stdout_file':
                                                       'stdout.out',
                                                       'partition':
                                                       'thinnodes',
                                                       'nodes': 4,
                                                       'tasks': 96,
                                                       'tasks_per_node': 24,
                                                       'memory': '4GB',
                                                       'qos': 'qos',
                                                       'reservation':
                                                          'croupier',
                                                       'mail_user':
                                                       'user@email.com',
                                                       'mail_type': 'ALL',
                                                       'max_time': '00:05:00',
                                                       'post': [
                                                          './cleanup1.sh',
                                                          './cleanup2.sh']},
                                                      self.logger)
        self.assertNotIn('error', response)
        self.assertIn('call', response)

        call = response['call']
        self.assertEqual(call, "module load mod1; ./some_script.sh; "
                               "sbatch --parsable -J 'test'"
                               " -e stderr.out"
                               " -o stdout.out"
                               " -t 00:05:00"
                               " -p thinnodes"
                               " -N 4"
                               " -n 96"
                               " --ntasks-per-node=24"
                               " --mem=4GB"
                               " --reservation=croupier"
                               " --qos=qos"
                               " --mail-user=user@email.com"
                               " --mail-type=ALL"
                               " cmd; "
                               "./cleanup1.sh; ./cleanup2.sh; ")

    def test_random_name(self):
        """ Random name formation. """
        name = self.wm._get_random_name('base')

        self.assertEqual(11, len(name))
        self.assertEqual('base_', name[:5])

    def test_random_name_uniqueness(self):
        """ Random name uniqueness. """
        names = []
        for _ in range(0, 50):
            names.append(self.wm._get_random_name('base'))

        self.assertEqual(len(names), len(set(names)))

    def test_parse_jobid(self):
        """ Parse JobID from sacct """
        parsed = self.wm._parse_states("test1|012345\n"
                                       "test2|123456\n"
                                       "test3|234567\n",
                                       None)

        self.assertDictEqual(parsed, {'test1': '012345',
                                      'test2': '123456',
                                      'test3': '234567'})

    def test_parse_clean_sacct(self):
        """ Parse no output from sacct """
        parsed = self.wm._parse_states("\n", None)

        self.assertDictEqual(parsed, {})


if __name__ == '__main__':
    unittest.main()
