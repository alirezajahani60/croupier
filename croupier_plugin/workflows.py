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

workflows.py - Holds the plugin workflows
'''

import sys
import time

from cloudify.decorators import workflow
from cloudify.workflows import ctx, api, tasks
from croupier_plugin.job_requester import JobRequester

LOOP_PERIOD = 1


class JobGraphInstance(object):
    """ Wrap to add job functionalities to node instances """

    def __init__(self, parent, instance):
        self._status = 'WAITING'
        self.parent_node = parent
        self.winstance = instance

        self.completed = not self.parent_node.is_job  # True if is not a job
        self.failed = False

        if parent.is_job:
            self._status = 'WAITING'

            # Get runtime properties
            runtime_properties = instance._node_instance.runtime_properties
            self.simulate = runtime_properties["simulate"]
            self.host = runtime_properties["credentials"]["host"]
            self.workdir = runtime_properties['workdir']

            # Decide how to monitor the job
            if runtime_properties["external_monitor_entrypoint"]:
                self.monitor_type = runtime_properties["external_monitor_type"]
                self.monitor_config = {
                    'url': ('http://' +
                            runtime_properties["external_monitor_entrypoint"] +
                            runtime_properties["external_monitor_port"])
                }
            else:  # internal monitoring
                self.monitor_type = runtime_properties["workload_manager"]
                self.monitor_config = runtime_properties["credentials"]

            self.monitor_period = int(runtime_properties["monitor_period"])

            # build job name
            instance_components = instance.id.split('_')
            self.name = runtime_properties["job_prefix"] +\
                instance_components[-1]
        else:
            self._status = 'NONE'
            self.name = instance.id
            self.monitor_url = ""

    def queue(self):
        """ Sends the job's instance to the workload manager queue """
        if not self.parent_node.is_job:
            return

        self.winstance.send_event('Queuing job..')
        result = self.winstance.execute_operation('croupier.interfaces.'
                                                  'lifecycle.queue',
                                                  kwargs={"name": self.name})
        result.task.wait_for_terminated()
        if result.task.get_state() == tasks.TASK_FAILED:
            init_state = 'FAILED'
        else:
            self.winstance.send_event('.. job queued')
            init_state = 'PENDING'
        self.set_status(init_state)
        return result.task

    def publish(self):
        """ Sends the job's instance to the workload manager queue """
        if not self.parent_node.is_job:
            return

        self.winstance.send_event('Publishing job outputs..')
        result = self.winstance.execute_operation('croupier.interfaces.'
                                                  'lifecycle.publish',
                                                  kwargs={"name": self.name})
        result.task.wait_for_terminated()
        if result.task.get_state() != tasks.TASK_FAILED:
            self.winstance.send_event('..outputs sent for publication')

        return result.task

    def set_status(self, status):
        """ Update the instance state """
        if not status == self._status:
            self._status = status
            self.winstance.send_event('State changed to ' + self._status)

            self.completed = not self.parent_node.is_job or \
                (self._status == 'COMPLETED')

            if self.completed:
                self.publish()

            if not self.parent_node.is_job:
                self.failed = False
            else:
                self.failed = self.parent_node.is_job and \
                    (self._status == 'BOOT_FAIL' or
                     self._status == 'CANCELLED' or
                     self._status == 'FAILED' or
                     self._status == 'REVOKED' or
                     self._status == 'TIMEOUT')

    def clean(self):
        """ Cleans job's aux files """
        if not self.parent_node.is_job:
            return

        self.winstance.send_event('Cleaning job..')
        result = self.winstance.execute_operation('croupier.interfaces.'
                                                  'lifecycle.cleanup',
                                                  kwargs={"name": self.name})
        # result.task.wait_for_terminated()
        self.winstance.send_event('.. job cleaned')

        # print result.task.dump()
        return result.task

    def cancel(self):
        """ Cancels the job instance of the workload manager """
        if not self.parent_node.is_job:
            return

        # First perform clean operation
        self.clean()

        self.winstance.send_event('Cancelling job..')
        result = self.winstance.execute_operation('croupier.interfaces.'
                                                  'lifecycle.cancel',
                                                  kwargs={"name": self.name})
        self.winstance.send_event('.. job canceled')
        result.task.wait_for_terminated()

        self._status = 'CANCELLED'


class JobGraphNode(object):
    """ Wrap to add job functionalities to nodes """

    def __init__(self, node, job_instances_map):
        self.name = node.id
        self.type = node.type
        self.cfy_node = node
        self.is_job = 'croupier.nodes.Job' in node.type_hierarchy

        if self.is_job:
            self.status = 'WAITING'
        else:
            self.status = 'NONE'

        self.instances = []
        for instance in node.instances:
            graph_instance = JobGraphInstance(self,
                                              instance)
            self.instances.append(graph_instance)
            if graph_instance.parent_node.is_job:
                job_instances_map[graph_instance.name] = graph_instance

        self.parents = []
        self.children = []
        self.parent_depencencies_left = 0

        self.completed = False
        self.failed = False

    def add_parent(self, node):
        """ Adds a parent node """
        self.parents.append(node)
        self.parent_depencencies_left += 1

    def add_child(self, node):
        """ Adds a child node """
        self.children.append(node)

    def queue_all_instances(self):
        """ Sends all job instances to the workload manager queue """
        if not self.is_job:
            return []

        tasks_list = []
        for job_instance in self.instances:
            tasks_list.append(job_instance.queue())

        self.status = 'QUEUED'
        return tasks_list

    def is_ready(self):
        """ True if it has no more dependencies to satisfy """
        return self.parent_depencencies_left == 0

    def _remove_children_dependency(self):
        """ Removes a dependency of the Node already satisfied """
        for child in self.children:
            child.parent_depencencies_left -= 1

    def check_status(self):
        """
        Check if all instances status

        If all of them have finished, change node status as well
        Returns True if there is no errors (no job has failed)
        """
        if not self.completed and not self.failed:
            if not self.is_job:
                self._remove_children_dependency()
                self.status = 'COMPLETED'
                self.completed = True
            else:
                completed = True
                failed = False
                for job_instance in self.instances:
                    if job_instance.failed:
                        failed = True
                        break
                    elif not job_instance.completed:
                        completed = False

                if failed:
                    self.status = 'FAILED'
                    self.failed = True
                    self.completed = False
                    return False

                if completed:
                    # The job node just finished, remove this dependency
                    self.status = 'COMPLETED'
                    self._remove_children_dependency()
                    self.completed = True

        return not self.failed

    def get_children_ready(self):
        """ Gets all children nodes that are ready to start """
        readys = []
        for child in self.children:
            if child.is_ready():
                readys.append(child)
        return readys

    def __str__(self):
        to_print = self.name + '\n'
        for instance in self.instances:
            to_print += '- ' + instance.name + '\n'
        for child in self.children:
            to_print += '    ' + child.name + '\n'
        return to_print

    def clean_all_instances(self):
        """ Cleans all job's files instances of the workload manager """
        if not self.is_job:
            return

        for job_instance in self.instances:
            job_instance.clean()
        self.status = 'CANCELED'

    def cancel_all_instances(self):
        """ Cancels all job instances of the workload manager """
        if not self.is_job:
            return

        for job_instance in self.instances:
            job_instance.cancel()
        self.status = 'CANCELED'


def build_graph(nodes):
    """ Creates a new graph of nodes and instances with the job wrapper """

    job_instances_map = {}

    # first create node structure
    nodes_map = {}
    root_nodes = []
    for node in nodes:
        new_node = JobGraphNode(node, job_instances_map)
        nodes_map[node.id] = new_node
        # check if it is root node
        try:
            node.relationships.next()
        except StopIteration:
            root_nodes.append(new_node)

    # then set relationships
    for _, child in nodes_map.iteritems():
        for relationship in child.cfy_node.relationships:
            parent = nodes_map[relationship.target_node.id]
            parent.add_child(child)
            child.add_parent(parent)

    return root_nodes, job_instances_map


class Monitor(object):
    """Monitor the instances"""

    def __init__(self, job_instances_map, logger):
        self.job_ids = {}
        self._execution_pool = {}
        self.timestamp = 0
        self.job_instances_map = job_instances_map
        self.logger = logger
        self.jobs_requester = JobRequester()

    def update_status(self):
        """Gets all executing instances and update their state"""

        # first get the instances we need to check
        monitor_jobs = {}
        for _, job_node in self.get_executions_iterator():
            if job_node.is_job:
                for job_instance in job_node.instances:
                    if not job_instance.simulate:
                        if job_instance.host in monitor_jobs:
                            monitor_jobs[job_instance.host]['names'].append(
                                job_instance.name)
                        else:
                            monitor_jobs[job_instance.host] = {
                                'config': job_instance.monitor_config,
                                'type': job_instance.monitor_type,
                                'workdir': job_instance.workdir,
                                'names': [job_instance.name],
                                'period': job_instance.monitor_period
                            }
                    else:
                        job_instance.set_status('COMPLETED')

        # nothing to do if we don't have nothing to monitor
        if not monitor_jobs:
            return

        # then look for the status of the instances through its name
        states = self.jobs_requester.request(monitor_jobs, self.logger)

        # finally set job status
        for inst_name, state in states.iteritems():
            self.job_instances_map[inst_name].set_status(state)

        # We wait to slow down the loop
        sys.stdout.flush()  # necessary to output work properly with sleep
        time.sleep(LOOP_PERIOD)

    def get_executions_iterator(self):
        """ Executing nodes iterator """
        return self._execution_pool.iteritems()

    def add_node(self, node):
        """ Adds a node to the execution pool """
        self._execution_pool[node.name] = node

    def finish_node(self, node_name):
        """ Delete a node from the execution pool """
        del self._execution_pool[node_name]

    def is_something_executing(self):
        """ True if there are nodes executing """
        return self._execution_pool


@workflow
def run_jobs(**kwargs):  # pylint: disable=W0613
    """ Workflow to execute long running batch operations """

    root_nodes, job_instances_map = build_graph(ctx.nodes)
    monitor = Monitor(job_instances_map, ctx.logger)

    # Execution of first job instances
    tasks_list = []
    for root in root_nodes:
        tasks_list += root.queue_all_instances()
        monitor.add_node(root)
    wait_tasks_to_finish(tasks_list)

    # Monitoring and next executions loop
    while monitor.is_something_executing() and not api.has_cancel_request():
        # Monitor the infrastructure
        monitor.update_status()
        exec_nodes_finished = []
        new_exec_nodes = []
        for node_name, exec_node in monitor.get_executions_iterator():
            if exec_node.check_status():
                if exec_node.completed:
                    exec_node.clean_all_instances()
                    exec_nodes_finished.append(node_name)
                    new_nodes_to_execute = exec_node.get_children_ready()
                    for new_node in new_nodes_to_execute:
                        new_exec_nodes.append(new_node)
            else:
                # Something went wrong in the node, cancel execution
                cancel_all(monitor.get_executions_iterator())
                return

        # remove finished nodes
        for node_name in exec_nodes_finished:
            monitor.finish_node(node_name)
        # perform new executions
        tasks_list = []
        for new_node in new_exec_nodes:
            tasks_list += new_node.queue_all_instances()
            monitor.add_node(new_node)
        wait_tasks_to_finish(tasks_list)

    if monitor.is_something_executing():
        cancel_all(monitor.get_executions_iterator())

    ctx.logger.info(
        "------------------Workflow Finished-----------------------")
    return


def cancel_all(executions):
    """Cancel all pending or running jobs"""
    for _, exec_node in executions:
        exec_node.cancel_all_instances()
    raise api.ExecutionCancelled()


def wait_tasks_to_finish(tasks_list):
    """Blocks until all tasks have finished"""
    for task in tasks_list:
        task.wait_for_terminated()
