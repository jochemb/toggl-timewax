#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A tool for synchronizing data between Timewax and
Toggl timekeeping services.

Author: Jochem Bijlard
"""

from __future__ import absolute_import, division, print_function

from toggl_timewax import __version__
from toggl_timewax.main import Toggl, Timewax

import logging
import os
import json
from getpass import getpass
import base64

import arrow
import appdirs
import click

from Crypto import Random, Hash, Cipher
import bcrypt

APP_NAME = u'toggl-timewax'
CONFIG_FILE = os.path.join(appdirs.user_config_dir(APP_NAME), 'config.json')
N_DAYS_DEFAULT = 9

logger = logging.getLogger(APP_NAME)
logging.basicConfig(level=logging.INFO,
                    format=u'%(asctime)s:%(name)s:%(levelname)s - %(message)s')


# Python 2/3 compatibility
try:
    input = raw_input
except NameError:
    pass


def sync_to_toggl(toggl, timewax):
    """
    For every project and breakdown available to your user in Timewax,
    create a project Toggl. This will use a naming convention to represent
    both the code and name of Timewax entities. The naming convention is
    subsequently used to send time entries in Toggl back to Timewax.
    This eliminates the need to ever go into Timewax to fill in hours.

    :param toggl: Toggl object.
    :param timewax: Timewax object.
    """
    logger.info(u'Now adding clients and projects to Toggl.')

    for client_project, project_breakdown in timewax.list_my_projects():

        if not toggl.has_client(client_project.toggl_name):
            toggl.add_client(client_project.toggl_name)

        toggl_client_id = toggl.get_client_id(client_project.toggl_name)

        if not toggl.client_has_project(project_breakdown.toggl_name, toggl_client_id):

            if timewax.check_breakdown_authorization(client_project, project_breakdown):
                toggl.add_project(toggl_client_id, project_breakdown.toggl_name)

    logger.info(u'Finished synchronizing projects from Timewax to Toggl.')


def sync_to_timewax(toggl, timewax, n_days=9):
    """
    Send over time entries made in Toggl to Timewax. This only works for entries made
    on projects imported from Timewax first.

    :param toggl: Toggl object.
    :param timewax: Timewax object.
    :param n_days: days in the past to sync entries.
    """

    recent_timewax = timewax.get_recent_entries(n_days)
    entries_to_update = []

    for toggl_entry in toggl.get_recent_entries(n_days):
        if not toggl_entry.stop:
            logger.info(u"Skipping entry: no stop date. It's probably running right now.")

        elif toggl_entry.guid not in recent_timewax:
            entries_to_update.append(toggl_entry)

        # check if different between Timewax entry and Toggl entry is greater than +60 seconds
        elif toggl_entry.duration - recent_timewax[toggl_entry.guid].duration > 60:
            logger.info(u'Entry found that has changed. Adding additional entry to compensate.')
            toggl_entry.duration -= recent_timewax[toggl_entry.guid].duration
            entries_to_update.append(toggl_entry)

        else:
            logger.info(u'Skipping previous entry: %r' % toggl_entry)

    if entries_to_update:
        timewax.add_entries(entries_to_update)

    logger.info(u'Finished synchronizing time entries from Toggl to Timewax.')


def get_toggl_timewax_from_ctx(ctx):
    """
    Use use and modify context and config to return tuple with applied
    config and toggl and timewax object

    :param ctx: click.Context object.
    :return: ctx, toggl, timewax
    """
    if not ctx.params['no_config'] and os.path.exists(CONFIG_FILE):
        config = read_config()
        logger.info('Using configuration created at: %s' % config.get('creation_date'))

    else:
        logger.info('Not using a configuration file. Continuing.')
        config = {}

    ctx.params['timewax_username'] = ctx.params['timewax_username'] or config.get('timewax_username')
    ctx.params['timewax_client'] = ctx.params['timewax_client'] or config.get('timewax_client')
    ctx.params['timewax_password'] = ctx.params['timewax_password'] or config.get('timewax_password')
    ctx.params['workspace_name'] = ctx.params['workspace_name'] or config.get('workspace_name')
    ctx.params['toggl_key'] = ctx.params['toggl_key'] or config.get('toggl_key')

    if ctx.params['n_days'] == N_DAYS_DEFAULT:
        ctx.params['n_days'] = config.get('n_days', N_DAYS_DEFAULT)

    logger.info('Connecting to Toggl and Timewax.')
    timewax = Timewax(ctx.params['timewax_username'],
                      ctx.params['timewax_password'],
                      ctx.params['timewax_client'])
    toggl = Toggl(ctx.params['toggl_key'], ctx.params['workspace_name'])

    return ctx, toggl, timewax


_global_test_options = [
    click.option('-u', '--timewax-username', type=str,
                 help='Your timewax username. Usually this is first letter ' +
                      'of firstname with the first four letters of lastname all uppercase.'),
    click.option('-p', '--timewax-password', type=str,
                 help='Your timewax password.'),
    click.option('-c', '--timewax-client', type=str,
                 help='Your timewax client (company) name.'),
    click.option('-k', '--toggl-key', type=str,
                 help='Your toggl api key.'),
    click.option('-w', '--workspace-name', type=str,
                 help='A name to match your available workspaces against. ' +
                      'The first one encountered will be picked. ' +
                      'Not necessary if you have only one workspace.'),
    click.option('-n', '--n-days', type=int, default=N_DAYS_DEFAULT,
                 help='Number of days in the past to look for time entries to send ' +
                      'from Toggl to Timewax (default: 9)'),
    click.option('--no-config', 'no_config', is_flag=True,
                 help='Do not read config, even if it is available.'),
    click.version_option(version='toggl-timewax synchroniser version %s.' % __version__)
]


def shared_options(func):
    for option in reversed(_global_test_options):
        func = option(func)
    return func


@click.group()
@shared_options
@click.pass_context
def cli(ctx, **kwargs):
    """
    Timewax-to-Toggl importer that creates projects in Toggl for each breakdown
    available in Timewax and can send Toggl time entries created for these projects
    to Timewax.

    Create a configuration file and encrypt Timewax and Toggl secrets. Needed
    for Timewax are your username, client (company) identifier, and password.
    For Toggl, only the API key is necessary, but if you have more than one
    workspace you need to provide a name to match it. Run:

        $ toggl-timewax generate_config

    Create Toggl projects for each project breakdown in Timewax:

        $ toggl-timewax to_toggl

    Keep track of time using your added client projects in Toggl. Update Timewax
    by running the following:

        $ toggl-timewax to_timewax
    """


@cli.command(short_help='Add time entries to Timewax.')
@shared_options
@click.pass_context
def to_timewax(ctx, **kwargs):
    """
    Send over time entries made in Toggl to Timewax. This only works for entries made
    on projects imported from Timewax first.
    """
    ctx, toggl, timewax = get_toggl_timewax_from_ctx(ctx)
    sync_to_timewax(toggl, timewax, ctx.params['n_days'])


@cli.command(short_help='Add projects to Toggl.')
@shared_options
@click.pass_context
def to_toggl(ctx, **kwargs):
    """
    For every project and breakdown available to your user in Timewax,
    create a project Toggl. This will use a naming convention to represent
    both the code and name of Timewax entities. The naming convention is
    subsequently used to send time entries in Toggl back to Timewax.
    This eliminates the need to ever go into Timewax to fill in hours.
    """
    ctx, toggl, timewax = get_toggl_timewax_from_ctx(ctx)
    sync_to_toggl(toggl, timewax)


@cli.command(short_help='Store secrets once.')
def generate_config(**kwargs):
    """
    Store necessary configuration in the user config directory on file system.
    From there it will be read automatically when a command is ran.
    """
    click.echo(u'Now creating config file. Please provide the following credentials: ')
    data = {
        'creation_date': arrow.now().format('YYYY-MM-DD HH:mm:ss'),
        'timewax_username': input('Timewax User identifier: '),
        'timewax_client': input('Timewax client: '),
        'workspace_name': input('Toggl workspace name to match, leave empty ' +
                                'to pick the first one encountered: '),
    }

    n_days = input(u'Number of days (INT) in the past to synchronize (default 9): ')
    if n_days:
        try:
            data['n_days'] = n_days
        except ValueError:
            logger.error(u'Has to be integer. Not saving n_days.')

    # Remove config items with empty response
    data = {k: v for k, v in data.items() if v}

    encrypt = ''
    while encrypt.lower() not in ('y', 'n'):
        encrypt = input(u'Do you want to store an encrypted password with the configuration.\n' +
                        u'You will be asked to create a new master password. (y/n)?')

    if encrypt.lower() == 'y':

        salt = bcrypt.gensalt()
        iv = Random.new().read(Cipher.AES.block_size)
        cipher = get_cipher(salt, iv)

        data.update({
            'encryption': {
                'salt': salt,
                'iv': base64.b64encode(iv).decode('utf-8'),
                'timewax_password': base64.b64encode(
                    cipher.encrypt(getpass('Timewax password: '))).decode('utf-8'),
                'toggl_key': base64.b64encode(
                    cipher.encrypt(getpass('Toggl API key: '))).decode('utf-8')
            }
        })

    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f)
        logger.info('Writing config to %s' % CONFIG_FILE)

    logger.info('Finished.')


def get_cipher(salt, iv):
    password = getpass('Enter master key: ')

    hashed_password = bcrypt.hashpw(password, salt)
    key = Hash.SHA256.new(hashed_password.encode('utf-8')).digest()
    cipher = Cipher.AES.new(key, Cipher.AES.MODE_CFB, iv)
    return cipher


def read_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    else:
        logger.info(u'Config file not found on disk.')
        return

    encryption_data = config.pop('encryption', None)
    if encryption_data:
        salt = encryption_data.get('salt')
        iv = base64.b64decode(encryption_data.get('iv'))
        cipher = get_cipher(salt, iv)

        try:
            timewax_password = base64.b64decode(encryption_data.get('timewax_password'))
            if timewax_password:
                config.update({'timewax_password': cipher.decrypt(timewax_password).decode('utf-8')})

            toggl_key = base64.b64decode(encryption_data.get('toggl_key'))
            if toggl_key:
                config.update({'toggl_key': cipher.decrypt(toggl_key).decode('utf-8')})
        except UnicodeDecodeError:
            raise SystemExit(u'Wrong password ¯\_(ツ)_/¯ ???')

    return config


if __name__ == "__main__":
    cli(obj={})
