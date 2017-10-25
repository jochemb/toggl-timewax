#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A tool for synchronizing data between Timewax and
Toggl timekeeping services.

Author: Jochem Bijlard
"""

from __future__ import absolute_import, division, print_function

from xml.etree import ElementTree
from xml.sax.saxutils import escape

from getpass import getpass
import logging
import re

import arrow
import requests
from requests.auth import HTTPBasicAuth

# Python 2/3 compatibility
try:
    input = raw_input
except NameError:
    pass

logger = logging.getLogger('toggl-timewax')
logging.basicConfig(level=logging.INFO,
                    format=u'%(asctime)s:%(name)s:%(levelname)s - %(message)s')


class EntryMismatchException(Exception):
    """
    This will be raise if a service provides unexpected response entries.
    """
    pass


class ClientProject(object):
    """
    Represents clients in Toggl and Projects in Timewax.
    """

    def __init__(self, name=None, timewax_code=None, wid=None, toggl_id=None):
        self.name = name
        self.timewax_code = timewax_code
        self.wid = wid
        self.toggl_id = toggl_id
        self.project_breakdowns = []

    @property
    def toggl_name(self):
        return self.timewax_code + ' - ' + self.name

    def to_json(self):
        """
        Creates json as needed for Toggl.
        """
        return {
            'client': {
                'name': self.toggl_name,
                'wid': self.wid
            }
        }

    @staticmethod
    def from_toggl(json_data):
        """
        Create object from json response from Toggl API. This raises EntryMismatchException
        if the client name does not match convention ("12345678 - Timewax project name")

        :param dict json_data: client response from Toggl API
        :return: ClientProject
        """
        try:
            code, name = json_data.get('name').split(' - ', 1)

            # Check whether the code is between 7 and 10 digits.
            # Otherwise raise AttributeError
            re.match(r'[0-9]{7,10}', code).end()

            return ClientProject(name=name,
                                 timewax_code=code,
                                 toggl_id=json_data.get('id'))

        except (ValueError, AttributeError):
            logger.error(u'Non Timewax client, found: %s' % json_data.get('name'))
            raise EntryMismatchException
    
    @staticmethod
    def from_timewax(xml_data):
        """
        Create object from xml response from timewax API.

        :param xml_data: should be ElementTree XML object.
        """
        return ClientProject(name=xml_data.find('name').text,
                             timewax_code=xml_data.find('code').text)

    def __repr__(self):
        return u'ClientProject(name=%s)' % self.name


class ProjectBreakdown(object):
    """
    Represents projects in Toggl and Breakdowns in Timewax.
    """

    def __init__(self, name=None, timewax_code=None, wid=None, toggl_id=None, toggl_client_id=None):
        self.name = name
        self.timewax_code = timewax_code
        self.wid = wid
        self.toggl_id = toggl_id
        self.toggl_client_id = toggl_client_id

    @property
    def toggl_name(self):
        return self.timewax_code + ' - ' + self.name

    def to_json(self):
        """
        Creates json as needed for Toggl.
        """
        return
                
    @staticmethod
    def from_toggl(json_data):
        """
        Create object from json response from toggl API.
        """
        try:
            code, name = json_data.get('name').split(' - ', 1)
            return ProjectBreakdown(name=name,
                                    timewax_code=code,
                                    toggl_client_id=json_data.get('cid'),
                                    toggl_id=json_data.get('id'))
        except ValueError:
            logger.error(u'Skipping non Timewax project found: %s' % json_data.get('name'))

    @staticmethod
    def from_timewax(xml_data):
        """
        Create object from xml response from timewax API.
        """
        return ProjectBreakdown(name=xml_data.find('name').text,
                                timewax_code=xml_data.find('code').text)

    def __repr__(self):
        return u'ProjectBreakdown(name=%s)' % self.name


class TimeEntry(object):
    """
    Object that is a time entry in Toggl, to be uploaded to Timewax.
    """
    
    TIMEWAX_TIME_FORMAT = 'HH:mm'

    def __init__(self, guid, description=None, duration=None, pid=None, 
                 start=None, stop=None, wid=None, resource=None, breakdown=None, project=None):
        """

        :param guid: as created by Toggl (mandatory)
        :param description: as put in Toggl
        :param duration: seconds
        :param pid: Toggl project identifier
        :param start: start_date
        :param stop: end_date
        :param wid: workspace identifier
        :param resource: Timewax user
        :param breakdown: Timewax code
        :param project: Timewax code
        """
    
        self.guid = guid

        self.description = description
        self.duration = duration
        self.pid = pid
        self.start = start
        self.stop = stop
        self.wid = wid
        self.resource = resource
        self.breakdown = breakdown
        self.project = project
    
    @property
    def date(self):
        date = arrow.get(self.start)
        return date.format(fmt=Timewax.DATE_FORMAT)
    
    @property
    def hours(self):
        return self.duration / (60 * 60)
    
    @property
    def start_time(self):
        date = arrow.get(self.start)
        return date.format(fmt=self.TIMEWAX_TIME_FORMAT)
    
    @property
    def end_time(self):
        date = arrow.get(self.stop)
        return date.format(fmt=self.TIMEWAX_TIME_FORMAT)
    
    @property
    def timewax_description(self):
        """ The description as to be loaded to Timewax """
        return (self.description or '') + ' ID:%s' % self.guid

    def __repr__(self):
        return u'TimeEntry(%s, %s, date=%s, start=%s, hours=%0.2f)' % \
               (self.project, self.breakdown, self.date, self.start_time, self.hours)
    
    def to_xml(self):
        return u"""
        <timeline>
            <resource>%s</resource>
            <project>%s</project>
            <breakdown>%s</breakdown>
            <date>%s</date>
            <hours>%s</hours>
            <startTime>%s</startTime>
            <endTime>%s</endTime>
            <description>%s</description>
        </timeline>
        """ % (self.resource, self.project, escape(self.breakdown), self.date, self.hours,
               self.start_time, self.end_time, escape(self.timewax_description))

    @staticmethod
    def from_timewax(xml_data):
        """
        Create object from timewax xml response. If there is no GUID in description, this will 
        raise EntryMismatchException.
        """
        desc = xml_data.find('description').text
        project = xml_data.find('project').text
        duration = float(xml_data.find('hours').text) * 60 * 60

        if desc and 'ID:' in desc:
            guid = desc.rsplit('ID:', 1)[-1]
        else:
            logger.warning(u'Time entry has no GUID and does not originate from Toggl. \n' +
                           u'Make sure to not add duplicate time entries manually!')
            raise EntryMismatchException

        return TimeEntry(guid=guid,
                         description=desc,
                         duration=duration,
                         project=project)


class Timewax(object):
    """
    Contains everything needed for connecting to Timewax.
    """

    DATE_FORMAT = u'YYYYMMDD'
    GET_TOKEN = u'https://api.timewax.com/authentication/token/get/'
    PROJECT_LIST = u'https://api.timewax.com/project/list/'
    BREAKDOWN_LIST = u'https://api.timewax.com/project/breakdown/list/'
    ENTRIES_LIST = u'https://api.timewax.com/time/entries/list/'
    ENTRIES_ADD = u'https://api.timewax.com/time/entries/add/'

    def __init__(self, timewax_id=None, timewax_key=None, client=None):
        self.timewax_id = timewax_id or input('Timewax username: ')
        self.timewax_key = timewax_key or getpass('Timewax password: ')
        self.client = client or input('Timewax client: ')

        self.token = self.get_token()

    def get_token(self):
        """
        Retrieves API token for further use.

        :return str: token
        """
        login = """
            <request>
                <client>%s</client>
                <username>%s</username>
                <password>%s</password>
            </request>""" % (self.client, self.timewax_id, self.timewax_key)

        r = requests.post(self.GET_TOKEN, data=login)
        root = ElementTree.fromstring(r.text)
        try:
            token = root.find("token").text
        except AttributeError:
            logger.error('Cannot login: ')
            logger.error(r.text)
            raise SystemExit
        return token

    def create_request(self, data):
        """
        Put data parameter inside xml string with request including token.

        :param data: xml string specific for the end point you want to use.
        :return: xml string including request and token.
        """
        return "<request><token>%s</token>%s</request>" % (self.token, data)

    def list_of_projects(self):
        """
        Yields project objects for projects visible to your user.

        :return: ClientProject generator
        """
        project_list = self.create_request(
            """<isParent></isParent>
               <isActive>Yes</isActive>
               <portfolio></portfolio>""")

        r = requests.post(self.PROJECT_LIST, data=project_list)

        root = ElementTree.fromstring(r.text)
        for project in root.find('projects'):
            yield ClientProject.from_timewax(project)

    def get_project_breakdowns(self, project_code):
        """
        Generator that gets ProjectBreakdowns for a certain project.

        :param str project_code: Timewax project code
        """
        request = self.create_request("<project>%s</project>" % project_code)
        r = requests.post(self.BREAKDOWN_LIST, data=request)

        if self.timewax_id in r.text:
            root = ElementTree.fromstring(r.text)

            for breakdown in root.find('breakdowns'):
                if breakdown.find('name').text:
                    yield ProjectBreakdown.from_timewax(breakdown)

    def list_my_projects(self):
        """
        Yields tuples for every available breakdown in Timewax.

        :return: (ClientProject, ProjectBreakdown)
        """
        for project in self.list_of_projects():
            for breakdown in self.get_project_breakdowns(project.timewax_code):
                yield project, breakdown

    def get_recent_entries(self, n_days=10):
        """
        Get your entries from a number of days ago until now (default 10).

        :param int n_days: days to look back for entries.
        """
        # Add a day to ensure no ensure no duplicates are created
        # as Timewax works using a less precise date format.
        n_days += 1

        n_days_ago = arrow.now().shift(days=-n_days).format(self.DATE_FORMAT)
        now = arrow.now().format(self.DATE_FORMAT)        
        logger.info('Getting Timewax entries since: %s' % n_days_ago)

        package = self.create_request(
            u"""<dateFrom>%s</dateFrom>
               <dateTo>%s</dateTo>
               <resource>%s</resource>
            """ % (n_days_ago, now, self.timewax_id))

        r = requests.post(self.ENTRIES_LIST, data=package)
        root = ElementTree.fromstring(r.text)
        
        entries = {}

        for xml_entry in root.find('entries'):
            
            try:
                time_entry = TimeEntry.from_timewax(xml_entry)
            except EntryMismatchException:
                continue

            # if there are multiple entries with the same GUID it means
            # a long entry in Toggl is represented as multiple small ones
            # in Timewax. This could be caused when a finished timer in Toggl
            # is changed manually after it is uploaded once.
            if time_entry.guid in entries:
                entries[time_entry.guid].duration += time_entry.duration
            else:
                entries.update({
                    time_entry.guid: time_entry
                })
        return entries

    def check_breakdown_authorization(self, project, breakdown):
        """
        Check if your user is authorized to book hours on a project.

        :param project: a ClientProject object.
        :param breakdown: a ProjectBreakdown object.
        :return bool: True or False
        """

        # Due to the limited Timewax api it is impossible to directly query for authorization.
        # Here we use a trick by trying to write a negative duration time entry. The API
        # will consider this a valid post request to the API but it will not return an identifier
        # for the time entry or write it to the database. In case the user is not authorised it
        # will return a non-valid.
        probe = TimeEntry(guid='not-quite-a-guid',
                          resource=self.timewax_id,
                          duration=-60,
                          project=project.timewax_code,
                          breakdown=breakdown.timewax_code)

        package = self.create_request(
            u'<timelines>%s</timelines>' % probe.to_xml())

        r = requests.post(self.ENTRIES_ADD, data=package)

        root = ElementTree.fromstring(r.text)
        if root.find('valid').text == 'yes':
            return True
        else:
            logger.info(u'Not authorised for %r - %r' % (project, breakdown))
            return False

    def add_entries(self, time_entries):
        """
        Add a list of TimeEntry objects to Timewax.

        :param time_entries: list of TimeEntry objects.
        """
        for entry in time_entries:
            entry.resource = self.timewax_id
            logger.info(u'To be added: %r' % entry)
        package = self.create_request(
            u'<timelines>%s</timelines>' % u''.join([e.to_xml() for e in time_entries]))

        r = requests.post(self.ENTRIES_ADD, data=package)
        
        root = ElementTree.fromstring(r.text)
        if root.find('valid').text == 'yes':
            logger.info(u'Successfully added %s entries.' % len(time_entries))
        else:
            logger.error(u'Unable to add entries to Timewax.')
            logger.info(r.text)


class Toggl(object):
    """
    Contains everything needed for connecting to Toggl.
    """

    CLIENTS = 'https://www.toggl.com/api/v8/clients'
    WORKSPACES = 'https://www.toggl.com/api/v8/workspaces'
    PROJECTS = 'https://www.toggl.com/api/v8/projects'
    TIME_ENTRIES = 'https://www.toggl.com/api/v8/time_entries'

    def __init__(self, api_key=None, workspace_name=None):
        self.toggl_key = api_key or getpass('Toggl api key: ')
        self.auth = HTTPBasicAuth(self.toggl_key, 'api_token')
        self.wid = self.get_workspace(workspace_name)
        self.clients = self.get_all_clients()
        self.projects = self.get_all_projects()

    def get_workspace(self, workspace_name=None):
        """ 
        Get the workspace identifier (wid). This tooling only supports
        a single workspace. Will pick the first workspace found.

        :param str workspace_name: text to match workspace name.
        :return int: workspace identifier.
        """
        r = requests.get(self.WORKSPACES, auth=self.auth)

        if workspace_name:
            w = [w for w in r.json() if workspace_name in w.get('name')]
        else:
            w = r.json()[0]

        logger.info(u'Using workspace named: %s' % w.get('name'))
        return w.get('id')

    def has_client(self, name):
        """
        Check whether client exists in Toggl by checking the self.clients dictionary.

        :param name: name of a Timewax client.
        :return bool: client exists or not.
        """
        return name in {client.toggl_name for client in self.clients.values()}

    def client_has_project(self, name, client_id):
        """
        Returns True or False whether client has project with name by checking the self.project dictionary.

        :param str name: project name
        :param int client_id: identifier for client
        :return bool: client has project or not.
        """
        if client_id not in self.clients:
            raise EntryMismatchException(u'No client with ID %s found' % client_id)
        projects = self.projects.get(client_id, {})
        return name in {p.toggl_name for p in projects.values()}

    def get_client_id(self, name):
        """ Get toggl identifier for client based on its name """
        for id_, client in self.clients.items():
            if client.toggl_name == name:
                return id_

    def get_all_clients(self):
        """ 
        Return dictionary of where keys are client 
        identifiers and values ClientProjects in Toggl. 
        """
        r = requests.get(self.CLIENTS, auth=self.auth)
        r_dict = {}
        for j in r.json():
            try:
                r_dict[j.get('id')] = ClientProject.from_toggl(j)
            except EntryMismatchException:
                pass
        return r_dict

    def get_timewax_project_breakdown(self, pid):
        """
        Get Timewax code and breakdown based on Toggl pid. This searches the self.projects
        dictionary for the project with given pid and its associated client identifier.
        It then returns a tuple with the two Timewax codes.

        :param int pid: project identifier
        :return tuple: (client.timewax_code, project.timewax_code)
        """
        for client_id, projects in self.projects.items():
            if pid in projects:
                break
        else:
            raise EntryMismatchException(u'Client not found for project %s' % pid)

        try:
            project_code = self.clients.get(client_id).timewax_code
            breakdown = projects.get(pid).timewax_code
            return project_code, breakdown
        except AttributeError:
            raise EntryMismatchException(u'Cannot find Timewax code for project %s' % projects.get(pid))

    def get_all_projects(self):
        """
        Builds dictionary with all ProjectBreakdowns currently available in Toggl. This
        dictionary has client identifiers as keys, and each value is another dictionary
        with project identifier as keys and ProjectBreakdown objects as value.

        :return dict: project dictionary.
        """
        r = requests.get(self.WORKSPACES + '/%s/projects' % self.wid,
                         params={'per_page': 1000,
                                 'active': 'both'},
                         auth=self.auth)
        
        project_dict = {}
        for p in r.json():
            client_id = p.get('cid')
            project_id = p.get('id')
            try:
                project_dict[client_id].update({project_id: ProjectBreakdown.from_toggl(p)})
            except KeyError:
                project_dict[client_id] = {project_id: ProjectBreakdown.from_toggl(p)}
        
        return project_dict

    def get_recent_entries(self, n_days=9):
        """
        Yield all entries with a start date of n_days (default: 9) days ago or fewer.

        :param int n_days: number of days to look back.
        :return: generator with TimeEntry objects.
        """

        n_days_ago = arrow.now().shift(days=-n_days)
        params = {u'start_date': n_days_ago.isoformat()}
        logger.info(u'Getting Toggl entries since: %s' % n_days_ago)

        r = requests.get(self.TIME_ENTRIES, params=params, auth=self.auth)
        for entry in r.json():
            project_id = entry.get('pid')
            if not project_id:
                continue

            try:
                project, breakdown = self.get_timewax_project_breakdown(project_id)
            except EntryMismatchException:
                logger.info(u'Skipping entry with mismatch, entry start (%s), description: %s' %
                            (entry.get('start'), entry.get('description')))
                continue

            yield TimeEntry(description=entry.get('description'),
                            duration=entry.get('duration'),
                            guid=entry.get('guid'),
                            start=entry.get('start'),
                            stop=entry.get('stop'),
                            wid=entry.get('wid'),
                            project=project,
                            breakdown=breakdown)

    def add_client(self, name):
        """
        Add client to Toggl.

        :param str name: name the client will have.
        """
        package = {
            'client': {
                'name': name,
                'wid': self.wid
            }
        }
        r = requests.post(self.CLIENTS, json=package, auth=self.auth)
        
        try:
            data = r.json().get('data')
        except ValueError:
            data = {}
        
        if name in data.get('name', ''):
            logger.info(u'Added client "%s" successfully.' % name)
            self.clients.update(
                {data.get('id'): ClientProject.from_toggl(data)}
            )
            self.projects.update(
                {data.get('id'): {}}
            )
        else:
            logger.info(u'Could not add client: %s' % r.text)

    def add_project(self, client_id, project_name):
        """
        Add project to Toggl for a given client based on its identifier.

        :param int client_id: Toggl id for client
        :param project_name: name for new project
        """
        
        package = {
            "project":
                {"name": project_name,
                 "wid": self.wid,
                 "is_private": True,
                 "cid": client_id
                 }
            }

        r = requests.post(self.PROJECTS, json=package, auth=self.auth)

        try:
            data = r.json().get('data')
        except ValueError:
            data = {}

        if project_name in data.get('name', ''):
            project_id = data.get('id')

            try:
                self.projects[client_id].update({project_id: ProjectBreakdown.from_toggl(data)})
            except KeyError:
                self.projects[client_id] = {project_id: ProjectBreakdown.from_toggl(data)}

            logger.info(u'Added project: %s ' % project_name)
        else:
            logger.info(u'Failed to add project "%s": %s' % project_name, r.text)
