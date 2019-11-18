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

workload_manager.py
'''

import string
import random
from datetime import datetime
from croupier_plugin.ssh import SshClient


BOOTFAIL = 0
CANCELLED = 1
COMPLETED = 2
CONFIGURING = 3
COMPLETING = 4
FAILED = 5
NODEFAIL = 6
PENDING = 7
PREEMPTED = 8
REVOKED = 9
RUNNING = 10
SPECIALEXIT = 11
STOPPED = 12
SUSPENDED = 13
TIMEOUT = 14
TASK_RUNNING = 15
TASK_FINISHED = 16
TASK_KILLED = 17

JOBSTATESLIST = [
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "CONFIGURING",
    "COMPLETING",
    "FAILED",
    "NODE_FAIL",
    "PENDING",
    "PREEMPTED",
    "REVOKED",
    "RUNNING",
    "SPECIAL_EXIT",
    "STOPPED",
    "SUSPENDED",
    "TIMEOUT",
    "TASK_RUNNING",
    "TASK_FINISHED",
    "TASK_KILLED",
]

JOBSTATESDICT = {
    "BOOT_FAIL": 0,
    "CANCELLED": 1,
    "COMPLETED": 2,
    "CONFIGURING": 3,
    "COMPLETING": 4,
    "FAILED": 5,
    "NODE_FAIL": 6,
    "PENDING": 7,
    "PREEMPTED": 8,
    "REVOKED": 9,
    "RUNNING": 10,
    "SPECIAL_EXIT": 11,
    "STOPPED": 12,
    "SUSPENDED": 13,
    "TIMEOUT": 14,
    "TASK_RUNNING": 15,
    "TASK_FINISHED": 16,
    "TASK_KILLED": 17,
}

_STATES_PRECEDENCE = [
    FAILED,
    NODEFAIL,
    BOOTFAIL,
    CANCELLED,
    REVOKED,
    TIMEOUT,
    SPECIALEXIT,
    STOPPED,
    SUSPENDED,
    PREEMPTED,
    RUNNING,
    CONFIGURING,
    PENDING,
    COMPLETING,
    COMPLETED,
    TASK_RUNNING,
    TASK_FINISHED,
    TASK_KILLED
]


def state_int_to_str(value):
    """state on its int value to its string value"""
    return JOBSTATESLIST[int(value)]


def state_str_to_int(value):
    """state on its string value to its int value"""
    return JOBSTATESDICT[value]


def get_prevailing_state(state1, state2):
    """receives two string states and decides which one prevails"""
    _st1 = state_str_to_int(state1)
    _st2 = state_str_to_int(state2)

    if _st1 == _st2:
        return state1

    for state in _STATES_PRECEDENCE:
        if _st1 == state or _st2 == state:
            return JOBSTATESLIST[state]

    return state1


class WorkloadManager(object):

    @staticmethod
    def factory(workload_manager):
        if workload_manager == "SLURM":
            from slurm import Slurm
            return Slurm()
        elif workload_manager == "TORQUE":
            from torque import Torque
            return Torque()
        elif workload_manager == "BASH":
            from bash import Bash
            return Bash()
        elif workload_manager == "SPARK":
            from spark import Spark
            return Spark()
        else:
            return None

    def submit_job(self,
                   ssh_client,
                   name,
                   job_settings,
                   is_singularity,
                   logger,
                   workdir=None,
                   context=None):
        """
        Sends a job to the HPC

        @type ssh_client: SshClient
        @param ssh_client: ssh client connected to an HPC login node
        @type name: string
        @param name: name of the job
        @type job_settings: dictionary
        @param job_settings: dictionary with the job options
        @type is_singularity: bool
        @param is_singularity: True if the job is in a container
        @rtype string
        @param logger: Logger object to print log messages
        @rtype logger
        @param workdir: Path of the working directory of the job
        @rtype string
        @param context: Dictionary containing context env vars
        @rtype dictionary of strings
        @return Slurm's job name sent. None if an error arise.
        """
        if not SshClient.check_ssh_client(ssh_client, logger):
            return False

        if is_singularity:
            # generate script content for singularity
            script_content = self._build_container_script(name,
                                                          job_settings,
                                                          logger)
            if script_content is None:
                return False

            if not self._create_shell_script(ssh_client,
                                             name + ".script",
                                             script_content,
                                             logger,
                                             workdir=workdir):
                return False

            # @TODO: use more general type names (e.g., BATCH/INLINE, etc)
            settings = {
                "type": "SBATCH",
                "command": name + ".script"
            }

            if 'scale' in job_settings:
                settings['scale'] = job_settings['scale']
                if 'scale_max_in_parallel' in job_settings:
                    settings['scale_max_in_parallel'] = \
                        job_settings['scale_max_in_parallel']
        else:
            settings = job_settings

        # build the call to submit the job
        response = self._build_job_submission_call(name,
                                                   settings,
                                                   logger)

        if 'error' in response:
            logger.error(
                "Couldn't build the call to send the job: " +
                response['error'])
            return False

        # prepare the scale env variables
        if 'scale_env_mapping_call' in response:
            scale_env_mapping_call = response['scale_env_mapping_call']
            output, exit_code = ssh_client.execute_shell_command(
                scale_env_mapping_call,
                workdir=workdir,
                wait_result=True)
            if exit_code != 0:
                logger.error("Scale env vars mapping '" +
                             scale_env_mapping_call +
                             "' failed with code " +
                             str(exit_code) + ":\n" + output)
                return False

        # submit the job
        call = response['call']
        if (settings['type'] == 'SPARK'):
            exit_code = ssh_client.execute_shell_command(
                call,
                env=context,
                workdir=workdir,
                wait_result=False)
            if exit_code is True:
                exit_code = 0
            logger.debug("Job execution with exit code : " + str(exit_code))
            import time
            time.sleep(30)
        else:
            output, exit_code = ssh_client.execute_shell_command(
                call,
                env=context,
                workdir=workdir,
                wait_result=True)
        # if (job_settings['type'] == 'SPARK'):
        #    output, exit_code = ssh_client.execute_shell_command(   \
        #        call, env=context, workdir=workdir, wait_result=False)
        # else:
        #    output, exit_code = ssh_client.execute_shell_command(   \
        #        call, env=context, workdir=workdir, wait_result=True)
        if exit_code != 0:
            logger.error("Job submission '" + call + "' exited with code " +
                         str(exit_code) + ":\n" + output)
            return False

        # Job is successfully submitted, get the framework ID info
        # to manage the jobs in future
        # if (settings['type'] == 'SPARK'):
            # Parse output to get the framework ID
        #    framework_id = _parse_spark_output(output)
            # Store framework_id in each executables
        return True

    def clean_job_aux_files(self,
                            ssh_client,
                            name,
                            job_options,
                            is_singularity,
                            logger,
                            workdir=None):
        """
        Cleans no more needed job files in the HPC

        @type ssh_client: SshClient
        @param ssh_client: ssh client connected to an HPC login node
        @type name: string
        @param name: name of the job
        @type job_settings: dictionary
        @param job_settings: dictionary with the job options
        @type is_singularity: bool
        @param is_singularity: True if the job is in a container
        @rtype string
        @return Slurm's job name stopped. None if an error arise.
        """
        if not SshClient.check_ssh_client(ssh_client, logger):
            return False

        if is_singularity:
            return ssh_client.execute_shell_command(
                "rm " + name + ".script",
                workdir=workdir)
        return True

    def stop_job(self,
                 ssh_client,
                 name,
                 job_options,
                 is_singularity,
                 logger,
                 workdir=None):
        """
        Stops a job from the HPC

        @type ssh_client: SshClient
        @param ssh_client: ssh client connected to an HPC login node
        @type name: string
        @param name: name of the job
        @type job_settings: dictionary
        @param job_settings: dictionary with the job options
        @type is_singularity: bool
        @param is_singularity: True if the job is in a container
        @rtype string
        @return Slurm's job name stopped. None if an error arise.
        """
        if not SshClient.check_ssh_client(ssh_client, logger):
            return False

        if job_options['type'] == "SPARK":
            call = self._build_job_cancellation_call(name, ssh_client,
                                                     logger)
        else:
            call = self._build_job_cancellation_call(name, job_options,
                                                     logger)
        if call is None:
            return False

        if not SshClient.check_ssh_client(ssh_client, logger):
            return False
        return ssh_client.execute_shell_command(
            call,
            workdir=workdir)

    def create_new_workdir(self, ssh_client, base_dir, base_name, logger):
        workdir = self._get_time_name(base_name)

        # we make sure that the workdir does not exists
        base_name = workdir
        while self._exists_path(ssh_client, base_dir + "/" + workdir):
            workdir = self._get_random_name(base_name)

        full_path = base_dir + "/" + workdir
        if ssh_client.execute_shell_command(
                "mkdir -p " + base_dir + "/" + workdir):
            return full_path
        else:
            logger.warning("Failed to create '" + base_dir +
                           "/" + workdir + "' directory.")
            return None

#   ################ ABSTRACT METHODS ################
    def _build_container_script(self,
                                name,
                                settings,
                                logger):
        """
        Creates a script to run Singularity

        @type name: string
        @param name: name of the job
        @type job_settings: dictionary
        @param job_settings: dictionary with the container job options
        @rtype string
        @return string with the batch script. None if an error arise.
        """
        raise NotImplementedError("'_build_container_script' not implemented.")

    def _build_job_submission_call(self,
                                   name,
                                   job_settings,
                                   logger):
        """
        Generates submission command line as a string

        @type name: string
        @param name: name of the job
        @type job_settings: dictionary
        @param job_settings: dictionary with the job options
        @rtype dict
        @return dict with two keys:
         'call' string to call slurm with its parameters, and
         'scale_env_mapping_call' to push the scale env variables on
         the batch scripts
            None if an error arise.
        """
        raise NotImplementedError(
            "'_build_job_submission_call' not implemented.")

    def _build_job_cancellation_call(self,
                                     name,
                                     job_settings,
                                     logger):
        """
        Generates cancel command line as a string

        @type name: string
        @param name: name of the job
        @type job_settings: dictionary
        @param job_settings: dictionary with the job options
        @rtype string
        @return string to call slurm with its parameters.
            None if an error arise.
        """
        raise NotImplementedError(
            "'_build_job_cancellation_call' not implemented.")

    # Monitor
    def get_states(self, ssh_client, names, logger):
        """
        Get the states of the jobs names

        @type credentials: dictionary
        @param credentials: dictionary with the HPC SSH credentials
        @type names: list
        @param names: list of the job names to retrieve their states
        @rtype dict
        @return a dictionary of job names and its states
        """
        raise NotImplementedError("'get_states' not implemented.")
#   ##################################################

    def _create_shell_script(self,
                             ssh_client,
                             name,
                             script_content,
                             logger,
                             workdir=None):
        # @TODO: why not to use ctx.download_resource and
        #        ssh_client.open_sftp().put(...)?
        # escape for echo command
        script_data = script_content \
            .replace("\\", "\\\\") \
            .replace("$", "\\$") \
            .replace("`", "\\`") \
            .replace('"', '\\"')

        create_call = "echo \"" + script_data + "\" >> " + name + \
            "; chmod +x " + name
        _, exit_code = ssh_client.execute_shell_command(
            create_call,
            workdir=workdir,
            wait_result=True)

        if exit_code != 0:
            logger.error(
                "failed to create script: call '" + create_call +
                "', exit code " + str(exit_code))
            return False

        return True

    def _get_random_name(self, base_name):
        """ Get a random name with a prefix """
        return base_name + '_' + self.__id_generator()

    def _get_time_name(self, base_name):
        """ Get a random name with a prefix """
        return base_name + '_' + datetime.utcnow().strftime('%Y%m%d_%H%M%S')

    def __id_generator(self,
                       size=6,
                       chars=string.digits + string.ascii_letters):
        return ''.join(random.SystemRandom().choice(chars)
                       for _ in range(size))

    def _exists_path(self, ssh_client, path):
        _, exit_code = ssh_client.execute_shell_command(
            '[ -d "' + path + '" ]',
            wait_result=True)

        if exit_code == 0:
            return True
        else:
            return False
