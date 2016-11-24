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

import threading
import time
import zmq

from supervisors.utils import TICK_HEADER, PROCESS_HEADER, STATISTICS_HEADER, supervisors_short_cuts


class EventSubscriber(object):
    """ Class for subscription to Listener events.

    Attributes:
    - supervisors: a reference to the Supervisors context,
    - socket: the PyZMQ subscriber. """

    def __init__(self, supervisors, zmq_context):
        """ Initialization of the attributes. """
        self.supervisors = supervisors
        self.socket = zmq_context.socket(zmq.SUB)
        # connect all EventPublisher to Supervisors addresses
        for address in supervisors.address_mapper.addresses:
            url = 'tcp://{}:{}'.format(address, supervisors.options.internal_port)
            supervisors.logger.info('connecting EventSubscriber to %s' % url)
            self.socket.connect(url)
        supervisors.logger.debug('EventSubscriber connected')
        self.socket.setsockopt(zmq.SUBSCRIBE, '')
 
    def receive(self):
        """ Reception of one message.
        First part is the message identifier.
        Second part is the body of the message, after pyobj unserialization. """
        return self.socket.recv_string(), self.socket.recv_pyobj()

    def disconnect(self, addresses):
        """ This method disconnects from the PyZMQ socket all addresses passed in parameter. """
        for address in addresses:
            url = 'tcp://{}:{}'.format(address, self.supervisors.options.internal_port)
            self.supervisors.logger.info('disconnecting EventSubscriber from %s' % url)
            self.socket.disconnect(url)

    def close(self):
        """ This method closes the PyZMQ socket. """
        self.socket.close()


class SupervisorsMainLoop(threading.Thread):
    """ Class for Supervisors main loop. All inputs are sequenced here.

    Attributes:
    - supervisors: a reference to the Supervisors context,
    - subscriber: the event subscriber,
    - loop: the infinite loop flag,
    - timer_event_time: the date used to trigger the periodic task. """

    def __init__(self, supervisors, zmq_context):
        """ Initialization of the attributes. """
        # thread attributes
        threading.Thread.__init__(self)
        # shortcuts
        self.supervisors = supervisors
        supervisors_short_cuts(self, ['fsm', 'logger', 'statistician'])
        # create event sockets
        self.subscriber = EventSubscriber(supervisors, zmq_context)
        supervisors.publisher.open(zmq_context)

    def stop(self):
        """ Request to stop the infinite loop by resetting its flag. """
        self.logger.info('request to stop main loop')
        self.loop = False

    # main loop
    def run(self):
        """ Contents of the infinite loop. """
        # create poller
        poller = zmq.Poller()
        # register event subscriber
        poller.register(self.subscriber.socket, zmq.POLLIN) 
        self.timer_event_time = time.time()
        # poll events every seconds
        self.loop = True
        while self.loop:
            socks = dict(poller.poll(1000))
            # check tick and process events
            if self.subscriber.socket in socks and socks[self.subscriber.socket] == zmq.POLLIN:
                self.logger.blather('got message on event subscriber')
                try:
                    message = self.subscriber.receive()
                except Exception, e:
                    self.logger.warn('failed to get data from subscriber: {}'.format(e.message))
                else:
                    if message[0] == TICK_HEADER:
                        self.logger.blather('got tick message: {}'.format(message[1]))
                        self.fsm.on_tick_event(message[1][0], message[1][1])
                    elif message[0] == PROCESS_HEADER:
                        self.logger.blather('got process message: {}'.format(message[1]))
                        self.fsm.on_process_event(message[1][0], message[1][1])
                    elif message[0] == STATISTICS_HEADER:
                        self.logger.blather('got statistics message: {}'.format(message[1]))
                        self.statistician.push_statistics(message[1][0], message[1][1])
            # check periodic task
            if self.timer_event_time + 5 < time.time():
                self.periodic_task()
            # publish all events from here using pyzmq json
        self.logger.info('exiting main loop')
        self.close()

    def periodic_task(self):
        """ Periodic task that mainly checks that addresses are still operating. """
        self.logger.blather('periodic task')
        addresses = self.fsm.on_timer_event()
        # disconnect isolated addresses from sockets
        self.subscriber.disconnect(addresses)
        # set date for next task
        self.timer_event_time = time.time()

    def close(self):
        """ This method closes the PyZMQ sockets. """
        self.supervisors.publisher.close()
        self.subscriber.close()

