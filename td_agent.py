#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Send results of fluentd monitor_agent plugin.
"""

import requests

from blackbird.plugins import base


class ConcreteJob(base.JobBase):

    def __init__(self, options, queue=None, logger=None):
        super(ConcreteJob, self).__init__(options, queue, logger)
        self.url = (
            'http://{host}:{port}/{uri}'
        ).format(
            host=self.options['monitor_plugin_host'],
            port=self.options['monitor_plugin_port'],
            uri=self.options['monitor_plugin_uri'],
        )

    def _enqueue(self, item):
        self.queue.put(item, block=False)
        self.logger.debug(
            'Inserted to queue {key}, {value}'
            ''.format(
                key=item.key,
                value=item.value
            )
        )

    def _get_monitor_agent_plugin(self, url):
        """
        Get monitor_agent plugin result by HTTP request.
        """
        try:
            response = requests.get(url, timeout=self.options['timeout'])
        except Exception:
            raise base.BlackbirdPluginError(
                'Maybe, fluentd doesn\'t load "monitor_agent" plugin.'
            )

        try:
            return response.json()
        except Exception:
            raise base.BlackbirdPluginError(
                'Response format is not json. Maybe, you specify invalid URI.'
            )

    def _generate_plugin_name(self, plugin_id, type):
        try:
            id = plugin_id.split(':')[1]
        except Exception:
            raise base.BlackbirdPluginError(
                'Maybe, plugin_id({0}) format is not "object:ID".'
                ''.format(plugin_id)
            )

        output_plugin = ':'.join(
            [
                type,
                id
            ]
        )
        return output_plugin

    def build_discovery_items(self):
        """
        Low level discovery loop.
        """
        response = self._get_monitor_agent_plugin(self.url)
        output_plugins = list()

        for entry in response['plugins']:
            if entry['output_plugin'] is True:
                plugin_name = self._generate_plugin_name(
                    plugin_id=entry['plugin_id'],
                    type=entry['type']
                )
                output_plugins.append(
                    plugin_name
                )

        if len(output_plugins) > 0:
            lld_item = base.DiscoveryItem(
                key='td-agent.plugins.LLD',
                value=[
                    {'{#PLUGIN}': entry} for entry in output_plugins
                ],
                host=self.options['hostname']
            )
            self._enqueue(lld_item)

    def build_items(self):
        """
        Main loop.
        """
        response = self._get_monitor_agent_plugin(self.url)

        for entry in response['plugins']:
            if (
                (entry['output_plugin'] is True)
                and
                ('buffer_queue_length' in entry.keys())
            ):
                plugin_name = self._generate_plugin_name(
                    plugin_id=entry['plugin_id'],
                    type=entry['type']
                )
                # generate queue length item
                buffer_queue_length = entry['buffer_queue_length']
                item = TdAgentItem(
                    key=(
                        'td-agent.buffer[{plugin_name},length]'
                        ''.format(plugin_name=plugin_name)
                    ),
                    value=buffer_queue_length,
                    host=self.options['hostname'],
                )
                self._enqueue(item)
                item = TdAgentItem(
                    key=(
                        'td-agent.buffer[{plugin_name},lps]'
                        ''.format(plugin_name=plugin_name)
                    ),
                    value=buffer_queue_length,
                    host=self.options['hostname'],
                )
                self._enqueue(item)

                # generate queue size(bytes) item
                buffer_queue_bytes = entry['buffer_total_queued_size']
                item = TdAgentItem(
                    key=(
                        'td-agent.buffer[{plugin_name},bytes]'
                        ''.format(plugin_name=plugin_name)
                    ),
                    value=buffer_queue_bytes,
                    host=self.options['hostname'],
                )
                self._enqueue(item)
                item = TdAgentItem(
                    key=(
                        'td-agent.buffer[{plugin_name},bps]'
                        ''.format(plugin_name=plugin_name)
                    ),
                    value=buffer_queue_bytes,
                    host=self.options['hostname'],
                )
                self._enqueue(item)

                # retry count
                item = TdAgentItem(
                    key=(
                        'td-agent.buffer[{plugin_name},retry_count]'
                        ''.format(plugin_name=plugin_name)
                    ),
                    value=entry['retry_count'],
                    host=self.options['hostname'],
                )
                self._enqueue(item)

                # generate plugin config items
                if 'config' in entry:
                    if 'buffer_queue_limit' in entry['config']:
                        buffer_queue_limit = (
                            entry['config']['buffer_queue_limit']
                        )

                    else:
                        self.logger.info(
                            (
                                '"buffer_queue_limit" doesn\'t exist '
                                'in "config" section.'
                            )
                        )
                        buffer_queue_limit = -1

                else:
                    self.logger.warn(
                        '"config" section doesn\'t exist.'
                    )
                    buffer_queue_limit = -1

                item = TdAgentItem(
                    key=(
                        'td-agent.config[{plugin_name},buffer_queue_limit]'
                        ''.format(plugin_name=plugin_name)
                    ),
                    value=buffer_queue_limit,
                    host=self.options['hostname'],
                )
                self._enqueue(item)


class TdAgentItem(base.ItemBase):
    """
    Enqueued item.
    Take key(used by zabbix) and value as argument.
    """

    def __init__(self, key, value, host):
        super(TdAgentItem, self).__init__(key, value, host)

        self.__data = {}
        self._generate()

    @property
    def data(self):
        """Dequeued data."""

        return self.__data

    def _generate(self):
        """
        Convert to the following format:
        TdAgentItem(key='uptime', value='65535')
        {host:host, key:key1, value:value1, clock:clock}
        """

        self.__data['key'] = self.key
        self.__data['value'] = self.value
        self.__data['host'] = self.host
        self.__data['clock'] = self.clock


class Validator(base.ValidatorBase):
    """
    This class store information
    which is used by validation config file.
    """

    def __init__(self):
        self.__spec = None

    @property
    def spec(self):
        self.__spec = (
            "[{0}]".format(__name__),
            "monitor_plugin_host = ipaddress(default='127.0.0.1')",
            "monitor_plugin_port = integer(0, 65535, default=24220)",
            "monitor_plugin_uri = string(default=api/plugins.json)",
            "timeout = integer(default=10)",
            "hostname = string(default={0})".format(self.detect_hostname())
        )
        return self.__spec


if __name__ == '__main__':
    OPTIONS = {
        'monitor_plugin_host': '127.0.0.1',
        'monitor_plugin_port': 24220,
        'monitor_plugin_uri': 'api/plugins.json',
        'timeout': 1
    }
    TDAGENT_JOB = ConcreteJob(options=OPTIONS)
    RESULT = TDAGENT_JOB._get_monitor_agent_plugin(
        TDAGENT_JOB.url
    )
    print(
        '{0}'.format(RESULT)
    )
