'''
A tool for synchronizing data between Timewax and
Toggl timekeeping services.

Author: Jochem Bijlard
'''

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import xml.etree.ElementTree as ET
from getpass import getpass
import uuid

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


class ClientProject(object):
    """
    Represents clients in Toggl and Projects in Timewax.
    """

    def __init__(self, name=None, timewax_code=None, wid=None, toggle_id=None):
        self.name = name
        self.timewax_code = timewax_code
        self.wid = wid
        self.toggle_id = toggle_id

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

class ProjectBreakdown(object):
    """
    Represents projects in Toggl and Breakdowns in Timewax.
    """
    
    def __init__(self, name=None, timewax_code=None, wid=None, toggle_id=None):
        self.name = name
        self.timewax_code = timewax_code
        self.wid = wid
        self.toggle_id = toggle_id

    @property
    def toggl_name(self):
        return self.timewax_code + ' - ' + self.name

    def to_json(self):
        """
        Creates json as needed for Toggl.
        """
        return


class Timewax(object):
    """
    Contains everything needed for connecting to Timewax.
    """

    DATE_FORMAT = 'YYYYMMDD'
    
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

        r = requests.post("https://api.timewax.com/authentication/token/get/", data=login)
        root = ET.fromstring(r.text)
        try:
            token = root.find("token").text
        except AttributeError:
            print(r.text)
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
        r = requests.post("https://api.timewax.com/project/list/", data=project_list)
        root = ET.fromstring(r.text)
        for project in root.find('projects'):
            yield ClientProject(name=project.find('name').text,
                                timewax_code=project.find('code').text)
            # code = project.find('code').text
            # name = project.find('name').text
            # shortname = project.find('shortName').text
            # yield code, name, shortname

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
        
        r = requests.post("https://api.timewax.com/project/breakdown/list/", data=request)
        if self.timewax_id not in r.text:
            return []

        root = ET.fromstring(r.text)
        # tuples = []
        # for breakdown in root.find('breakdowns'):
        #     name = breakdown.find('name').text
        #     code = breakdown.find('code').text
        #     tuples += [(name, code)]
        # return tuples
        for breakdown in root.find('breakdowns'):
            if breakdown.find('name').text:
                yield ProjectBreakdown(name=breakdown.find('name').text,
                                       timewax_code=breakdown.find('code').text)

    def list_my_projects(self):
        """
        Returns tuples for every available breakdown in Timewax:
          (ClientProject, ProjectBreakdown)
        """
        # for project_code, project_name, shortname in self.list_of_projects():
        for project in self.list_of_projects():
            # for breakdown_name, breakdown_code in self.get_project_breakdowns(project.timewax_code):
            for breakdown in self.get_project_breakdowns(project.timewax_code):
                # yield project_code, project_name, breakdown_code, breakdown_name
                yield project, breakdown


    def get_recent_entries(self):
        """ Get your entries from 10 days ago untill now. """

        ten_days_ago = arrow.now().shift(days=-10).format(self.DATE_FORMAT)
        now = arrow.now().format(self.DATE_FORMAT)

        package = """
        <request>
            <token>{}</token>
            <dateFrom>{}</dateFrom>
            <dateTo>{}</dateTo>
            <resource>{}</resource>
        </request>
        """.format(self.token, ten_days_ago, now, self.timewax_id)

        r = requests.post("https://api.timewax.com/time/entries/list/", data=package)
        root = ET.fromstring(r.text)
        
        entries = {}

        for entry in root.find('entries'):
            desc = entry.find('description').text
            project = entry.find('project').text
            hours = float(entry.find('hours').text)

            if desc and 'ID:' in desc:
                guid = desc.rsplit('ID:', 1)[-1]
            else:
                guid = str(uuid.uuid4())

            if guid in entries:
                entries[guid]['hours'] += hours
            else:
                entries.update({
                    guid: {
                        'description': desc, 
                        'project': project,
                        'hours': hours}
                })
        return entries

    def add_entries(self, time_entries):
        for entry in time_entries:
            entry.resource = self.timewax_id
        package = """
        <request>
            <token>{}</token>
            <timelines>{}</timelines>
        </request>
        """.format(self.token, ''.join([e.to_xml() for e in time_entries]))
        r = requests.post("https://api.timewax.com/time/entries/add/", data=package)
        root = ET.fromstring(r.text)
        if root.find('valid').text == 'yes':
            print('Succesfully added {} entries.'.format(len(time_entries)))
        else:
            print(r.text)


class Toggl(object):
    """
    Contains everything needed for connecting to Toggl.
    """
    
    CLIENTS = 'https://www.toggl.com/api/v8/clients'
    WORKSPACES = 'https://www.toggl.com/api/v8/workspaces'
    PROJECTS = 'https://www.toggl.com/api/v8/projects'
    TIME_ENTRIES = 'https://www.toggl.com/api/v8/time_entries'
    
    def __init__(self, api_key=None):
        self.toggl_key = api_key or getpass('Toggle api key: ')
        self.auth = HTTPBasicAuth(self.toggl_key, 'api_token')
        self.wid = self.get_workspace()
        self.clients = self.get_all_clients()
        self.projects = self.get_all_projects()

    def get_workspace(self):
        r = requests.get(self.WORKSPACES, auth=self.auth)
        w = r.json()[0]
        print('Using workspace named: ' + str(w.get('name')))
        return w.get('id')

    def has_client(self, name):
        return name in {v for k, v in self.clients.items()}

    def client_has_project(self, name, client_id):
        assert client_id in self.clients
        projects = self.projects.get(client_id, {})
        return name in {v for k, v in projects.items()}

    def get_client_id(self, name):
        return {v: k for k, v in self.clients.items()}.get(name)

    def get_all_clients(self):
        r = requests.get(self.CLIENTS, auth=self.auth)
        return {j.get('id'): j.get('name') for j in r.json()}
        return {j.get('id'): j.get('name') for j in r.json()}

    def get_timewax_project_breakdown(self, pid):
        for client_id, projects in self.projects.items():
            if pid in projects:
                break
        else:
            raise Exception('Client not found for project {}'.format(pid))
        
        project_code = self.clients.get(client_id).split(' -')[0]
        breakdown = projects.get(pid).split(' -')[0]
        return project_code, breakdown

    def get_all_projects(self):
        r = requests.get(self.WORKSPACES + '/{}/projects'.format(self.wid),
                         params={'per_page': 1000,
                                 'active': 'both'},
                         auth=self.auth)
        
        project_dict = {}
        for p in r.json():
            client_id = p.get('cid')
            project_name = p.get('name')
            project_id = p.get('id')
            try:
                project_dict[client_id].update({project_id: project_name})
            except KeyError:
                project_dict[client_id] = {project_id: project_name}
        
        return project_dict

    def get_recent_entries(self):
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
                            breakdown=breakdown     
                            )
    
    def add_client(self, name):
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
            print(u'Added client {!r} successfully.'.format(str(name)))
            self.clients.update(
                {data.get('id'): data.get('name')}
            )
            self.projects.update(
                {data.get('id'): {}}
            )
        else:
            print(u'Could not add client: ' + str(r.text))
            
    def add_project(self, client_id, project_name):
        
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
                self.projects[client_id].update({project_id: project_name})
            except KeyError:
                self.projects[client_id] = {project_id: project_name}

            print('Added project: ' + str(project_name))
        else:
            print('Failed to add project {!r}: {}'.format(project_name, r.text))


class TimeEntry(object):
    
    def __init__(self, description=None, duration=None, guid=None, pid=None, 
            start=None, stop=None, wid=None, resource=None, breakdown=None, project=None):
    
        self.description = description
        self.duration = duration
        self.guid = guid
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
        return date.format(fmt='HH:mm')
    
    @property
    def end_time(self):
        date = arrow.get(self.stop)
        return date.format(fmt='HH:mm')
    
    @property
    def desc(self):
        return self.description + ' ID:{}'.format(self.guid)
    
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
                   self.hours, self.start_time, self.end_time, self.desc)


@click.group()
@click.version_option(prog_name="toggle-timewax synchronizer by {}".format(__author__))
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

    # for project_code, project_name, breakdown_code, breakdown_name in timewax.list_my_projects():
    for client_project, project_breakdown in timewax.list_my_projects():

        if not toggl.has_client(client_project.toggl_name):
            toggl.add_client(client_project.toggl_name)

        toggl_client_id = toggl.get_client_id(client_project.toggl_name)

        if not toggl.client_has_project(project_breakdown.toggl_name, toggl_client_id):
            toggl.add_project(toggl_client_id, project_breakdown.toggl_name)

    print("Finished synchronizing.")


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
            print("Skipping entry: no stop date.")

        elif toggl_entry.guid not in recent_timewax:
            entries_to_update.append(toggl_entry)

        elif toggl_entry.hours - recent_timewax[toggl_entry.guid]['hours'] > 0.2:
            toggl_entry.hours -= recent_timewax[toggl_entry.guid]['hours']
            entries_to_update.append(toggl_entry)

        else:
            print("Skipping entry: already present.")

    if entries_to_update:
        timewax.add_entries(entries_to_update)

    print("Finished synchronizing.")


if __name__ == "__main__":
    cli()
