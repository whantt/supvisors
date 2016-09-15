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

from supervisor.states import *

from supervisors.types import ApplicationStates, StartingFailureStrategies, RunningFailureStrategies


class ApplicationRules(object):
    """ Definition of the rules for starting an application, iaw deployment file:
    - autostart: a boolean telling if the application is to be started when Supervisors enters in DEPLOYMENT state,
    - sequence: defines the order of this application when starting all the applications in the DEPLOYMENT state,
    - starting_failure_strategy: defines the strategy (in StartingFailureStrategies) to apply when a required process cannot be strated during the starting of the application,
    - running_failure_strategy: defines the strategy (in RunningFailureStrategies) to apply when a required process crashes when the application is running. """

    def __init__(self):
        """ Initializes the rules applicable to an application"""
        self.autostart = False
        # TODO: implement sequence
        self.sequence = -1
        # TODO: implement starting failure strategy
        self.starting_failure_strategy = StartingFailureStrategies.ABORT
        # TODO: implement running failure strategy
        self.running_failure_strategy = RunningFailureStrategies.CONTINUE

    def __str__(self):
        """ Contents as string """
        return 'autostart={} starting_failure_strategy={} running_failure_strategy={}'.format(self.autostart, self.starting_failure_strategy, self.running_failure_strategy)


# ApplicationStatus class
class ApplicationStatus(object):
    """ Class defining the status of an application of Supervisors with the following information:
    - application_name: the name of the application, corresponding to the Supervisor group name,
    - state: the state of the application in ApplicationStates,
    - major_failure: a status telling if a required process is stopped while the application is running,
    - minor_failure: a status telling if an optional process has crashed while the application is running,
    - processes: the map (key is process name) of the ProcessStatus belonging to the application,
    - rules: the ApplicationRules instance applicable to the application,
    - sequence: the sequencing to start the processes belonging to the application, as a dictionary. The value corresponds to a list of processes having the same sequence order, used as key. """

    def __init__(self, application_name, logger):
        """ Initialization of the attributes. """
        # keep reference to common logger
        self.logger = logger
        # information part
        self.application_name = application_name
        self._state = ApplicationStates.UNKNOWN
        self.major_failure = False
        self.minor_failure = False
        # process part
        self.processes = {} # {process_name: [process]}
        self.rules = ApplicationRules()
        self.sequence = {} # {sequence: [process]}

    # access
    def running(self):
        """ Return True if application is running. """
        return self.state in [ApplicationStates.STARTING, ApplicationStates.RUNNING]

    def stopped(self):
        """ Return True if application is stopped. """
        return self.state in [ApplicationStates.UNKNOWN, ApplicationStates.STOPPED]
 
    @property
    def state(self):
        """ Property for the 'state' attribute. """
        return self._state

    @state.setter
    def state(self, newState):
        if self._state != newState:
            self._state = newState
            self.logger.info('Application {} is {}'.format(self.application_name, self.state_string()))

    # serialization
    def to_json(self):
        """ Return a JSON-serializable form of the ApplicationStatus. """
        return { 'application_name': self.application_name, 'state': self.state_string(),
            'major_failure': self.major_failure, 'minor_failure': self.minor_failure }

    # methods
    def state_string(self):
        """ Return the application state as a string. """
        return ApplicationStates._to_string(self.state)

    def add_process(self, process):
        """ Add a new process to the process list. """
        self.processes[process.process_name] = process

    def sequence_deployment(self):
        """ Evaluate the application sequencing from its list of processes. """
        # fill ordering iaw process rules
        self.sequence.clear()
        for process in self.processes.values():
            self.sequence.setdefault(process.rules.sequence, []).append(process)
        self.logger.debug('Application {}: sequence={}'.format(self.application_name, self.sequence))

    def update_status(self):
        """ Update the state of the application iaw the state of its processes. """
        starting, running, stopping, major_failure, minor_failure = (False, )*5
        for process in self.processes.values():
            self.logger.trace('Process {}: state={} required={} exit_expected={}'.
                format(process.namespec(), process.state_string(), process.rules.required, process.expected_exit))
            if process.state == ProcessStates.RUNNING:
                running = True
            elif process.state in [ProcessStates.STARTING, ProcessStates.BACKOFF]:
                starting = True
            # STOPPING is not in STOPPED_STATES
            elif process.state == ProcessStates.STOPPING:
                stopping = True
            # a FATAL required (resp. optional) process is a major (resp. minor) failure for application
            # similarly, an EXITED process is a major (resp. minor) failure for application if required (resp. optional) and exit code not expected
            elif (process.state == ProcessStates.FATAL) or (process.state == ProcessStates.EXITED and not process.expected_exit):
               if process.rules.required:
                   major_failure = True
               else:
                   minor_failure = True
            # all other STOPPED-like states are considered normal
        self.logger.trace('Application {}: starting={} running={} stopping={} major_failure={} minor_failure={}'.
            format(self.application_name, starting, running, stopping, major_failure, minor_failure))
        # apply rules for state
        if starting:
            self.state = ApplicationStates.STARTING
        elif stopping:
            self.state = ApplicationStates.STOPPING
        elif running:
            self.state = ApplicationStates.RUNNING
        else:
            self.state = ApplicationStates.STOPPED
        # update major_failure and minor_failure status (only for running applications)
        self.major_failure = major_failure and self.running()
        self.minor_failure = minor_failure and self.running()
