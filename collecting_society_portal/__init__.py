# For copyright and license terms, see COPYRIGHT.rst (top level of repository)
# Repository: https://github.com/C3S/collecting_society.portal

"""
Main module for the pyramid app.
"""

import os
import logging
from logging.config import fileConfig

from pyramid.config import Configurator
from pyramid.authentication import AuthTktAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid_beaker import session_factory_from_settings

from .config import (
    replace_environment_vars,
    get_plugins,
    notfound
)
from .models import (
    Tdb,
    WebUser
)
from .resources import (
    WebRootFactory,
    ApiRootFactory
)

log = logging.getLogger(__name__)


def main(global_config, **settings):
    """
    Configures and creates the app.

    Handles configuration of

    - app config
    - tryton database
    - session
    - policies
    - subscribers
    - route predicates
    - view predicates
    - request methods
    - translation directories
    - logging
    - root factories
    - resources
    - registry
    - views

    Contains the main logic of the plugin system by including settings,
    translation directories, logging configuration, views, ressources and
    registry information of the plugins in a well defined order.

    Args:
        global_config (dict): Parsed [DEFAULT] section of .ini file.
        **settings (dict): Parsed [app:main] section of .ini file.

    Returns:
        obj: a Pyramid WSGI application.
    """

    # get plugin configuration
    plugins = get_plugins(settings)

    # update portal settings with plugin settings and replace environment vars
    for priority in sorted(plugins, reverse=True):
        settings.update(plugins[priority]['settings'])
    settings = replace_environment_vars(settings)

    # init app config
    config = Configurator(settings=settings)

    # configure tryton database
    Tdb._db = settings['tryton.database']
    Tdb._company = settings['tryton.company']
    Tdb._user = settings['tryton.user']
    Tdb._configfile = settings['tryton.configfile']
    Tdb.init()

    # configure session
    config.set_session_factory(factory=session_factory_from_settings(settings))

    # configure policies
    config.set_authorization_policy(policy=ACLAuthorizationPolicy())
    config.set_authentication_policy(
        policy=AuthTktAuthenticationPolicy(
            secret=settings['authentication.secret'],
            hashalg='sha512',
            callback=WebUser.groupfinder
        )
    )
    config.set_default_permission('administrator')

    # configure subscribers
    config.add_subscriber(
        subscriber='.config.add_templates',
        iface='pyramid.events.BeforeRender'
    )
    config.add_subscriber(
        subscriber='.config.add_helpers',
        iface='pyramid.events.BeforeRender'
    )
    config.add_subscriber(
        subscriber='.config.add_locale',
        iface='pyramid.events.NewRequest'
    )
    if settings['env'] == 'development':
        config.add_subscriber(
            subscriber='.config.debug_request',
            iface='pyramid.events.NewRequest'
        )
        config.add_subscriber(
            subscriber='.config.debug_response',
            iface='pyramid.events.NewResponse'
        )

    # configure route predicates
    config.add_route_predicate(
        name='environment',
        factory='.config.Environment'
    )

    # configure view predicates
    config.add_view_predicate(
        name='environment',
        factory='.config.Environment'
    )

    # configure request methods
    config.add_request_method(
        callable=WebUser.current_web_user,
        name='user',
        reify=True
    )

    # configure translation directories for portal and plugins
    config.add_translation_dirs(
        'colander:locale/',
        'deform:locale/',
        'collecting_society_portal:locale/'
    )
    for priority in sorted(plugins):
        translation_dir = os.path.join(
            plugins[priority]['path'],
            plugins[priority]['name'],
            'locale'
        )
        if os.path.isdir(translation_dir):
            config.add_translation_dirs(translation_dir)

    # configure logging for portal and plugins
    for priority in sorted(plugins):
        fileConfig(
            plugins[priority]['path'] + '/' + settings['env'] + '.ini',
            disable_existing_loggers=False
        )

    # commit config with basic settings
    config.commit()

    # not found view (404 Error)
    config.add_notfound_view(notfound)

    # configure webfrontend for portal and plugins
    if settings['service'] == 'portal':
        # web root factory
        config.set_root_factory(factory=WebRootFactory)
        # web resources
        config.include('.includes.web_resources')
        for priority in sorted(plugins):
            config.include(
                plugins[priority]['name']+'.includes.web_resources'
            )
        # web registry
        config.include('.includes.web_registry')
        for priority in sorted(plugins):
            config.include(
                plugins[priority]['name']+'.includes.web_registry'
            )
        # web views
        for priority in sorted(plugins, reverse=True):
            config.include(
                plugins[priority]['name'] + '.includes.web_views'
            )
        config.include('.includes.web_views')
        # api views
        if settings['api.in_web'] == 'true':
            config.include('cornice')
            for priority in sorted(plugins, reverse=True):
                config.include(
                    plugins[priority]['name'] + '.includes.api_views',
                    route_prefix=settings['api.in_web_path']
                )
            config.include(
                '.includes.api_views',
                route_prefix=settings['api.in_web_path']
            )

    # configure api for portal and plugins
    if settings['service'] == 'api':
        config.include('cornice')
        # api root factory
        config.set_root_factory(factory=ApiRootFactory)
        # api views
        for priority in sorted(plugins, reverse=True):
            config.include(
                plugins[priority]['name'] + '.includes.api_views'
            )
        config.include('.includes.api_views')

    return config.make_wsgi_app()
