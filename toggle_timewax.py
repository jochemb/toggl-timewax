'''
A tool for synchronizing data between Timewax and
Toggl timekeeping services.

Author: Jochem Bijlard
'''

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import xml.etree.ElementTree as ET
from getpass import getpass
import logging

import arrow
import requests
from requests.auth import HTTPBasicAuth
import click

__author__ = 'Jochem Bijlard'
__version__ = '0.1'

# Python 2/3 compatibility
try:
    input = raw_input
except NameError:
    pass

logger = logging.getLogger('toggl-timewax')
logging.basicConfig(level=logging.INFO)


class EntryMismatchException(Exception):
    """ This will be raise if a service provides unexpected response entries. """
    pass

class ClientProjectBreakdownContainer(object):
    """
    Class that is used as a container for all ClientProjects and ProjectBreakdowns
    """
    def __init__(self):
        self.clients = []

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
            'client':{
                'name': self.toggl_name,
                'wid': self.wid
            }
        }

    @staticmethod
    def from_toggl(json_data):
        """
        Create object from json response from toggl API.
        """
        code, name = json_data.get('name').split(' - ', 1)
        return ClientProject(name=name,
                             timewax_code=code,
                             toggl_id=json_data.get('id'))
    
    @staticmethod
    def from_timewax(xml_data):
        """
        Create object from xml response from timewax API.

        :param xml_data: should be ElementTree XML object.
        """
        return ClientProject(name=xml_data.find('name').text,
                             timewax_code=xml_data.find('code').text)

    def __repr__(self):
        return 'ClientProject(name={}, code={})'.format(self.name, self.timewax_code)


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
        code, name = json_data.get('name').split(' - ', 1)
        return ProjectBreakdown(name=name,
                                timewax_code=code,
                                toggl_client_id=json_data.get('cid'),
                                toggl_id = json_data.get('id'))

    @staticmethod
    def from_timewax(xml_data):
        """
        Create object from xml response from timewax API.
        """
        return ProjectBreakdown(name=xml_data.find('name').text,
                                timewax_code=xml_data.find('code').text)

    def __repr__(self):
        return 'ProjectBreakdown(name={}, code={})'.format(self.name, self.timewax_code)


class TimeEntry(object):
    """
    Object that is a time entry in Toggl, to be uploaded to Timewax.
    """
    
    TIMEWAX_TIME_FORMAT = 'HH:mm'

    def __init__(self, guid, description=None, duration=None, pid=None, 
            start=None, stop=None, wid=None, resource=None, breakdown=None, project=None):
    
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
        return (self.description or '') + ' ID:{}'.format(self.guid)
    
    def to_xml(self):
        return """
        <timeline>
            <resource>{}</resource>
            <project>{}</project>
            <breakdown>{}</breakdown>
            <date>{}</date>
            <hours>{}</hours>
            <startTime>{}</startTime>
            <endTime>{}</endTime>
            <description>{}</description>
        </timeline>
        """.format(self.resource, self.project, self.breakdown, self.date,
                   self.hours, self.start_time, self.end_time, self.timewax_description)

    @staticmethod
    def from_timewax(xml_data):
        """
        Create object from timewax xml response. If there is no GUID in description, this will 
        raise EntryMismatchException.
        """
        desc = xml_data.find('description').text
        project = xml_data.find('project').text
        hours = float(xml_data.find('hours').text)

        if desc and 'ID:' in desc:
            guid = desc.rsplit('ID:', 1)[-1]
        else:
            logger.warning('Time entry has no GUID and does not originate from Toggl. \n' +
                           'Make sure to not add duplicate time entries manually!')
            raise EntryMismatchException

        return TimeEntry(guid=guid,
                         description=desc,
                         duration=hours,
                         project=project)


class Timewax(object):
    """
    Contains everything needed for connecting to Timewax.
    """

    DATE_FORMAT = 'YYYYMMDD'
    GET_TOKEN = "https://api.timewax.com/authentication/token/get/"
    PROJECT_LIST = "https://api.timewax.com/project/list/"
    BREAKDOWN_LIST = "https://api.timewax.com/project/breakdown/list/"
    ENTRIES_LIST = "https://api.timewax.com/time/entries/list/"
    ENTRIES_ADD = "https://api.timewax.com/time/entries/add/"

    def __init__(self, timewax_id=None, timewax_key=None, client=None):
        self.timewax_id = timewax_id or input('Timewax username: ')
        self.timewax_key = timewax_key or getpass('Timewax password: ')
        self.client = client or input('Timewax client: ')

        self.token = self.get_token()

    def get_token(self):
        """
        Retrieves API token for further use.
        """
        login = """
            <request>
                <client>{}</client>
                <username>{}</username>
                <password>{}</password>
            </request>""".format(self.client, self.timewax_id, self.timewax_key)

        r = requests.post(self.GET_TOKEN, data=login)
        root = ET.fromstring(r.text)
        try:
            token = root.find("token").text
        except AttributeError:
            logger.error('Cannot login: ')
            logger.error(r.text)
        return token
    
    def list_of_projects(self):
        """
        Returns generator that yields project objects.
        """
        project_list = """
            <request>
                <token>{}</token>
                <isParent></isParent>
                <isActive>Yes</isActive>
                <portfolio></portfolio>
            </request>""".format(self.token)
        r = requests.post(self.PROJECT_LIST, data=project_list)

        root = ET.fromstring(r.text)
        for project in root.find('projects'):
            yield ClientProject.from_timewax(project)

    def get_project_breakdowns(self, project_code: str) -> ProjectBreakdown:
        """
        Generator that gets ProjectBreakdowns for a certain project.

        :param str project_code: Timewax project code
        """
        request = """
            <request>
                <token>{}</token>
                <project>{}</project>
            </request>""".format(self.token, project_code)

        r = requests.post(self.BREAKDOWN_LIST, data=request)
        if self.timewax_id not in r.text:
            return []

        root = ET.fromstring(r.text)

        for breakdown in root.find('breakdowns'):
            if breakdown.find('name').text:
                yield ProjectBreakdown.from_timewax(breakdown)

    def list_my_projects(self):
        """
        Returns tuples for every available breakdown in Timewax:
          (ClientProject, ProjectBreakdown)
        """
        for project in self.list_of_projects():
            for breakdown in self.get_project_breakdowns(project.timewax_code):
                yield project, breakdown

    def get_recent_entries(self, days_past=10):
        """ Get your entries from (default 10) days ago until now. """

        ten_days_ago = arrow.now().shift(days=-days_past).format(self.DATE_FORMAT)
        now = arrow.now().format(self.DATE_FORMAT)

        package = """
        <request>
            <token>{}</token>
            <dateFrom>{}</dateFrom>
            <dateTo>{}</dateTo>
            <resource>{}</resource>
        </request>
        """.format(self.token, ten_days_ago, now, self.timewax_id)

        r = requests.post(self.ENTRIES_LIST, data=package)
        root = ET.fromstring(r.text)
        
        entries = {}

        for xml_entry in root.find('entries'):
            
            try:
                time_entry = TimeEntry.from_timewax(xml_entry)
            except EntryMismatchException:
                pass

            if time_entry.guid in entries:
                entries[time_entry.guid].duration += time_entry.duration
            else:
                entries.update({
                    time_entry.guid: time_entry
                })
        return entries

    def add_entries(self, time_entries):
        """ Add a list of TimeEntry objects to Timewax """
        for entry in time_entries:
            entry.resource = self.timewax_id
        package = """
        <request>
            <token>{}</token>
            <timelines>{}</timelines>
        </request>
        """.format(self.token, ''.join([e.to_xml() for e in time_entries]))
        r = requests.post(self.ENTRIES_ADD, data=package)
        
        root = ET.fromstring(r.text)
        if root.find('valid').text == 'yes':
            logger.info('Succesfully added {} entries.'.format(len(time_entries)))
        else:
            logger.error('Unable to add entries to Timewax.')
            logger.debug(r.text)


class Toggl(object):
    """
    Contains everything needed for connecting to Toggl.
    """

    CLIENTS = 'https://www.toggl.com/api/v8/clients'
    WORKSPACES = 'https://www.toggl.com/api/v8/workspaces'
    PROJECTS = 'https://www.toggl.com/api/v8/projects'
    TIME_ENTRIES = 'https://www.toggl.com/api/v8/time_entries'

    def __init__(self, api_key=None):
        self.toggl_key = api_key or getpass('Toggl api key: ')
        self.auth = HTTPBasicAuth(self.toggl_key, 'api_token')
        self.wid = self.get_workspace()
        self.clients = self.get_all_clients()
        self.projects = self.get_all_projects()

    def get_workspace(self):
        r = requests.get(self.WORKSPACES, auth=self.auth)
        w = r.json()[0]
        logger.info('Using workspace named: %s' % w.get('name'))
        return w.get('id')

    def has_client(self, name):
        """ check whether client exists """
        return name in {client.toggl_name for client in self.clients.values()}

    def client_has_project(self, name, client_id):
        """ returns True or False whether client has project with name """
        assert client_id in self.clients
        projects = self.projects.get(client_id, {})
        return name in {p.toggl_name for p in projects.values()}

    def get_client_id(self, name):
        """ Get toggl identifier for client based on its name """
        for id_, client in self.clients.items():
            if client.toggl_name == name:
                return id_

    def get_all_clients(self):
        """ Return list of all ClientProjects in Toggl. """
        r = requests.get(self.CLIENTS, auth=self.auth)
        return {j.get('id'): ClientProject.from_toggl(j) for j in r.json()}

    def get_timewax_project_breakdown(self, pid):
        """ get timewax code and breakdown based on toggl pid """
        for client_id, projects in self.projects.items():
            if pid in projects:
                break
        else:
            raise Exception('Client not found for project {}'.format(pid))
        
        project_code = self.clients.get(client_id).timewax_code
        breakdown = projects.get(pid).timewax_code
        return project_code, breakdown

    def get_all_projects(self):
        """ builds dictionary with all ProjectBreakdowns currently avialable in Toggl """
        r = requests.get(self.WORKSPACES + '/{}/projects'.format(self.wid),
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

    def get_recent_entries(self):
        """ Get all entries with a start date of 9 days ago or fewer """
        r = requests.get(self.TIME_ENTRIES, auth=self.auth)
        for entry in r.json():
            project, breakdown = self.get_timewax_project_breakdown(entry.get('pid'))
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
        """
        package = {
            'client':{
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
            logger.info('Added client "%s" successfully.' % name)
            self.clients.update(
                {data.get('id'): ClientProject.from_toggl(data)}
            )
            self.projects.update(
                {data.get('id'): {}}
            )
        else:
            logger.info('Could not add client: %s' % r.text)
            
    def add_project(self, client_id, project_name):
        """ Add project to Toggle for a given client """
        
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
                self.projects[client_id].update({project_id: ProjectBreakdown(data)})
            except KeyError:
                self.projects[client_id] = {project_id: ProjectBreakdown(data)}

            logger.info('Added project: %s ' % project_name)
        else:
            logger.info('Failed to add project "%s": %s' % project_name, r.text)


@click.group()
@click.version_option(prog_name="toggl-timewax synchronizer by %s" % __author__)
def cli():
    """     
    Timewax-to-Toggl importer that creates projects in Toggl for each breakdown
    available in Timewax.
    """
    pass


@cli.command()
@click.option('-u', '--timewax-username', type=str,
              help='Your timewax username. Usually this is first letter ' +
              'of firstname with the first four letters of lastname all uppercase.')
@click.option('-p', '--timewax-password', type=str,
              help='Your timewax password.')
@click.option('-c', '--timewax-client', type=str,
              help='Your timewax client (company) name.')
@click.option('-k', '--toggl-key', type=str,
              help='Your toggl api key.')
def to_toggl(timewax_username=None,
             timewax_password=None,
             timewax_client=None,
             toggl_key=None):
    """
    Add projects in Toggl for each breakdown in Timewax.
    """
    toggl = Toggl(toggl_key)
    timewax = Timewax(timewax_username, timewax_password, timewax_client)

    for client_project, project_breakdown in timewax.list_my_projects():

        if not toggl.has_client(client_project.toggl_name):
            toggl.add_client(client_project.toggl_name)

        toggl_client_id = toggl.get_client_id(client_project.toggl_name)

        if not toggl.client_has_project(project_breakdown.toggl_name, toggl_client_id):
            toggl.add_project(toggl_client_id, project_breakdown.toggl_name)

    logger.info("Finished synchronizing.")


@cli.command()
@click.option('-u', '--timewax-username', type=str,
              help='Your timewax username. Usually this is first letter ' +
              'of firstname with the first four letters of lastname all uppercase.')
@click.option('-p', '--timewax-password', type=str,
              help='Your timewax password.')
@click.option('-c', '--timewax-client', type=str,
              help='Your timewax client (company) name.')
@click.option('-k', '--toggl-key', type=str,
              help='Your toggl api key.')
def to_timewax(timewax_username=None,
               timewax_password=None,
               timewax_client=None,
               toggl_key=None):
    """
    Upload records to Timewax.
    """
    toggl = Toggl(toggl_key)
    timewax = Timewax(timewax_username, timewax_password, timewax_client)

    recent_timewax = timewax.get_recent_entries()
    entries_to_update = [] 

    for toggl_entry in toggl.get_recent_entries():
        if not toggl_entry.stop:
            logger.info("Skipping entry: no stop date.")

        elif toggl_entry.guid not in recent_timewax:
            entries_to_update.append(toggl_entry)

        elif toggl_entry.hours - recent_timewax[toggl_entry.guid]['hours'] > 0.2:
            toggl_entry.hours -= recent_timewax[toggl_entry.guid]['hours']
            entries_to_update.append(toggl_entry)

        else:
            logger.info("Skipping entry: already present.")

    if entries_to_update:
        timewax.add_entries(entries_to_update)

    logger.info("Finished synchronizing.")


if __name__ == "__main__":
    cli()
